// Import the constants from the module.
import * as constants from "../scripts/constants.js";

// Import the required components from the Lit Library 
import { LitElement, html, css } from '../scripts/lit/lit-core.min.js';

// Import component styles
import { onOffSwitchStyles, sharedStyles, actionButtonStyles, patternsListStyles, patternLinkStyles } from "./styles.js";

/**
 * The object to access the API functions of the browser.
 * @constant
 * @type {{runtime: object, tabs: object, i18n: object}} BrowserAPI
 */
const brw = chrome;

/**
 * An enum-like object that defines numbers for activation states of the extension.
 * @constant
 * @type {Object.<string, number>}
 */
const activationState = Object.freeze({
    On: 1,
    Off: 0,
    PermanentlyOff: -1,
});

// Add an event handler that processes incoming messages.
// Expected messages to the popup are the results of the pattern detection from the content script.
brw.runtime.onMessage.addListener(
    function (message, sender, sendResponse) {
        // Pass the message to the corresponding method of the `ExtensionPopup` component.
        document.querySelector("extension-popup").handleMessage(message, sender, sendResponse);
    }
);

/**
 * A function to get information about the currently opened tab.
 * The current tab is always the tab in which the popup was opened.
 * When the tab is changed, the popup is also closed automatically.
 * @returns {Promise.<{url: string, id: number, windowId: number}>}
 */
async function getCurrentTab() {
    return (await brw.tabs.query({ active: true, currentWindow: true }))[0];
}

/**
 * Merges per-frame getPatternsResults()-shaped objects into one combined
 * result. content.js now runs in every frame (manifest.json's
 * content_scripts has `all_frames: true`, so iframe-embedded dark patterns
 * — e.g. an embedded cookie-consent widget — get scanned too), so each
 * frame reports independently via its own message and must be summed here
 * rather than the popup just keeping whichever message arrived last.
 * Element phids are only unique WITHIN one frame (each frame's own
 * addPhidForEveryElement counter starts at 0), so they're rewritten here to
 * "<frameId>:<phid>"; ShowPatternButtons.showPattern() below decodes that
 * prefix to target the right frame when jumping to an element.
 * @param {Map<number, object>} frameResults frameId -> raw per-frame result
 * @returns {object} Combined {patterns, countVisible, count}
 */
function mergeFrameResults(frameResults) {
    const patternsByName = new Map();
    let countVisible = 0;
    let count = 0;
    for (const [frameId, result] of frameResults) {
        countVisible += result.countVisible || 0;
        count += result.count || 0;
        for (const pattern of result.patterns || []) {
            const existing = patternsByName.get(pattern.name) || { name: pattern.name, elementsVisible: [], elementsHidden: [] };
            existing.elementsVisible = existing.elementsVisible.concat(
                pattern.elementsVisible.map((phid) => `${frameId}:${phid}`)
            );
            existing.elementsHidden = existing.elementsHidden.concat(
                pattern.elementsHidden.map((phid) => `${frameId}:${phid}`)
            );
            patternsByName.set(pattern.name, existing);
        }
    }
    return { patterns: Array.from(patternsByName.values()), countVisible, count };
}

/**
 * Lit component for the entire popup.
 * Uses all other Lit components defined below.
 * @extends LitElement
 */
export class ExtensionPopup extends LitElement {
    // From the Lit documentation (https://lit.dev/docs/components/properties/):
    // "Reactive properties are properties that can trigger the reactive update cycle when changed,
    // re-rendering the component, and optionally be read or written to attributes.".
    static properties = {
        // Variable for the internal activation state of the extension for the current tab.
        // Can be set by the on/off switch.
        activation: { type: Number },
        // Variable for the initial activation state of the extension for the current tab.
        // Will only be changed after a new activation state is sent to the background script and the page is refreshed.
        initActivation: { type: Number },
        // Variable for the results of the pattern detection from the content script.
        results: { type: Object }
    };

    constructor() {
        super();
        // Check if the pattern configuration is valid.
        if (!constants.patternConfigIsValid) {
            // If the configuration is not valid, the content script does not start the pattern highlighting
            // and the extension is permanently disabled. Therefore set the status to permanently off.
            this.activation = activationState.PermanentlyOff;
        } else {
            // Otherwise, set the activation state to off by default.
            // This will be overwritten with the true status later.
            this.activation = activationState.Off;
        }
        this.initActivation = this.activation;
        // Set the results initially to an empty dictionary. The true results will be loaded later.
        this.results = {};
        // Raw per-frame results (frameId -> message), merged into
        // `this.results` via mergeFrameResults() on every update — see its
        // docstring above for why a straight overwrite is wrong once
        // content.js also runs inside iframes.
        this._frameResults = new Map();
    }

    /**
     * Function to process incoming messages.
     * @param {object} message The received message.
     * @param {MessageSender} sender Data about the sender of the message.
     * @param {function} sendResponse Function to send a reply.
     */
    async handleMessage(message, sender, sendResponse) {
        // Check if the message contains results from the pattern detection.
        if ("countVisible" in message) {
            // Check if the message was sent by the active tab from the current window.
            if (sender.tab.active && (await getCurrentTab()).windowId === sender.tab.windowId) {
                // Record this frame's results and recombine with every
                // other frame's latest results (main frame + any iframes).
                this._frameResults.set(sender.frameId, message);
                this.results = mergeFrameResults(this._frameResults);
            }
        }
    }

    /**
     * From the Lit documentation (https://lit.dev/docs/components/lifecycle/):
     * "Called after the element's DOM has been updated the first time, immediately before `updated()` is called.".
     * This function is used to load and set the activation state and results.
     * Since asynchronous methods are used for this, this is not done in the constructor.
     */
    async firstUpdated() {
        // Check if the activation state has already been set as permanently disabled
        // due to an invalid configuration.
        if (this.activation === activationState.PermanentlyOff) {
            // If yes, then exit the function.
            return;
        }
        // Load data about the current tab.
        let currentTab = await getCurrentTab();
        // Load the activation state and results, if the tab contains a web page loaded with HTTP(S),
        // which means that the extension's content script will be injected.
        if (currentTab.url.toLowerCase().startsWith("http://") || currentTab.url.toLowerCase().startsWith("https://")) {
            // Load the activation state.
            let currentTabActivation = await brw.runtime.sendMessage({ "action": "getActivationState", "tabId": currentTab.id });
            // Only do more, if the extension is activated.
            if (currentTabActivation.isEnabled) {
                // Set the activation state to on.
                this.activation = activationState.On;

                // In case the popup was opened before the web page was fully loaded in the tab,
                // the request of the results fails because the content script cannot respond yet.
                // Therefore, the request is repeated until it is successful.
                while (true) {
                    try {
                        // Load the results of the pattern detection.
                        // frameId: 0 is required, not optional — without it,
                        // tabs.sendMessage broadcasts to EVERY frame in the
                        // tab (all_frames: true means that now includes ad/
                        // tracking iframes) and returns whichever frame's
                        // content script happens to answer first, which is
                        // not necessarily the main frame. Any iframe's own
                        // results still arrive separately via
                        // handleMessage()'s push and get merged in then.
                        const mainFrameResult = await brw.tabs.sendMessage(currentTab.id, { action: "getPatternCount" }, { frameId: 0 });
                        this._frameResults.set(0, mainFrameResult);
                        this.results = mergeFrameResults(this._frameResults);
                        // Break out of the infinite loop if the request did not throw an error.
                        break;
                    } catch (error) {
                        // Wait for 250 milliseconds.
                        await new Promise(resolve => { setTimeout(resolve, 250) });
                    }
                }
            }
        } else {
            // If the extension's content script is not injected, set the activation state to permanently off,
            // because in this case the extension cannot be activated.
            this.activation = activationState.PermanentlyOff;
        }
        // Set the initial activation state to the state just loaded at initialization.
        this.initActivation = this.activation;
    }

    /**
     * Render the HTML of the component.
     * @returns {html} HTML of the component
     */
    render() {
        return html`
            <popup-header></popup-header>
            <on-off-switch .activation=${this.activation} .app=${this}></on-off-switch>
            <redo-button .activation=${this.initActivation}></redo-button>
            <report-button .activation=${this.initActivation}></report-button>
            <found-patterns-list .activation=${this.initActivation} .results=${this.results}></found-patterns-list>
            <show-pattern-button .activation=${this.initActivation} .results=${this.results}></show-pattern-button>
            <supported-patterns-list></supported-patterns-list>
            <popup-footer></popup-footer>
        `;
    }
}
// Define a custom element for the component so that it can be used in the HTML DOM.
customElements.define("extension-popup", ExtensionPopup);

/**
 * Lit component for the header/title of the popup.
 * @extends LitElement
 */
export class PopupHeader extends LitElement {
    // CSS styles for the HTML elements in the component.
    // Colors match the Kali brand palette (frontend/src/index.css's
    // .kali-light theme: cream background, olive-gold primary).
    static styles = [
        sharedStyles,
        css`
            .brand {
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 8px;
                margin: 12px auto 4px;
            }

            .brand img {
                width: 28px;
                height: 28px;
                object-fit: contain;
            }

            .brand span {
                font-family: "Cormorant Garamond", Georgia, serif;
                font-weight: 700;
                font-size: 1.6em;
                letter-spacing: 0.15em;
                color: #8D9518;
            }

            h3 {
                color: #D92626;
            }
        `
    ];

    /**
     * Render the HTML of the component.
     * @returns {html} HTML of the component
     */
    render() {
        return html`
        <div class="brand">
            <img src="../images/kali-logo.png" alt="${brw.i18n.getMessage("extName")}">
            <span>KALI</span>
        </div>
        ${!constants.patternConfigIsValid ?
                html`<h3>${brw.i18n.getMessage("errorInvalidConfig")}<h3>` : html``}
      `;
    }
}
// Define a custom element for the component so that it can be used in the HTML DOM.
customElements.define("popup-header", PopupHeader);

/**
 * Lit component for the on/off switch of the popup.
 * @extends LitElement
 */
export class OnOffSwitch extends LitElement {
    // Reactive properties
    static properties = {
        // Variable for the activation state of the component.
        activation: { type: Number },
        // Variable for the reference to the parent component.
        app: { type: Object }
    };

    // CSS styles for the HTML elements in the component.
    static styles = [
        sharedStyles,
        onOffSwitchStyles
    ];

    /**
     * Function that handles a change of the on/off switch value.
     * Applies the new activation state immediately (persisted in the
     * background script and live-toggled in the content script), so no
     * page reload is required for the change to take effect.
     * @param {Event} event
     */
    async changeActivation(event) {
        if (this.activation !== activationState.PermanentlyOff) {
            if (this.activation === activationState.Off) {
                this.activation = activationState.On;
            } else {
                this.activation = activationState.Off;
            }
            this.app.activation = this.activation;

            const enabled = this.activation === activationState.On;
            const tabId = (await getCurrentTab()).id;
            // Persist the new activation state for this tab in the background script.
            await brw.runtime.sendMessage({ "enableExtension": enabled, "tabId": tabId });
            // Apply the change live in the content script, without a page reload.
            await brw.tabs.sendMessage(tabId, { "setActivation": enabled });

            this.app.initActivation = this.activation;
        }
    }

    /**
     * Render the HTML of the component.
     * @returns {html} HTML of the component
     */
    render() {
        return html`
        <div>
            <input type="checkbox" id="main-onoffswitch" tabindex="0"
                @change=${this.changeActivation}
                .checked=${this.activation === activationState.On}
                .disabled=${this.activation === activationState.PermanentlyOff} />
            <label for="main-onoffswitch">
                <span class="onoffswitch-inner"></span>
                <span class="onoffswitch-switch"></span>
            </label>
        </div>
      `;
    }
}
// Define a custom element for the component so that it can be used in the HTML DOM.
customElements.define("on-off-switch", OnOffSwitch);

/**
 * Lit component for the redo button of the popup.
 * @extends LitElement
 */
export class RedoButton extends LitElement {
    // Reactive properties
    static properties = {
        // Variable for the activation state of the component.
        activation: { type: Number }
    };

    // CSS styles for the HTML elements in the component.
    static styles = [
        sharedStyles,
        actionButtonStyles
    ];

    /**
     * Function to trigger the pattern detection in the tab again.
     * @param {Event} event
     */
    async redoPatternCheck(event) {
        await brw.tabs.sendMessage((await getCurrentTab()).id, { action: "redoPatternHighlighting" });
    }

    /**
     * Render the HTML of the component.
     * @returns {html} HTML of the component
     */
    render() {
        // Return an empty string if the component is not activated.
        if (this.activation !== activationState.On) {
            return html``;
        }
        return html`
        <div>
            <span @click=${this.redoPatternCheck}>${brw.i18n.getMessage("buttonRedoPatternCheck")}</span>
        </div>
      `;
    }
}
// Define a custom element for the component so that it can be used in the HTML DOM.
customElements.define("redo-button", RedoButton);

/**
 * Lit component for the "create PDF report" button of the popup.
 * @extends LitElement
 */
export class ReportButton extends LitElement {
    // Reactive properties
    static properties = {
        // Variable for the activation state of the component.
        activation: { type: Number }
    };

    // CSS styles for the HTML elements in the component.
    static styles = [
        sharedStyles,
        actionButtonStyles
    ];

    /**
     * Fetches the current findings from the content script, captures a
     * screenshot of the visible tab (best-effort — report.js falls back to
     * "no screenshot" if this fails, e.g. on a chrome:// page; note this is
     * the visible viewport only, not the full scrollable page — a Chrome
     * extension API limitation, not a choice), stores both for the report
     * page to read, and opens that page in a new tab. The report page then
     * triggers the browser's print dialog so the user can save it as a
     * PDF — no PDF library, no backend call.
     * @param {Event} event
     */
    async createReport(event) {
        const tab = await getCurrentTab();
        // frameId: 0 is required, not optional — see the identical comment
        // on the getPatternCount call in firstUpdated() above. Without it,
        // an ad/tracking iframe on the page could answer instead of the
        // real page, corrupting the report's url/findings with the iframe's
        // own (e.g. a raw ad-network tracking URL as `url`).
        const reportData = await brw.tabs.sendMessage(tab.id, { action: "getReportData" }, { frameId: 0 });
        let screenshot = null;
        try {
            screenshot = await brw.tabs.captureVisibleTab(tab.windowId, { format: "png" });
        } catch (e) {
            // best-effort, see docstring above.
        }
        await brw.storage.local.set({ reportData: { ...reportData, screenshot } });
        await brw.tabs.create({ url: brw.runtime.getURL("report/report.html") });
    }

    /**
     * Render the HTML of the component.
     * @returns {html} HTML of the component
     */
    render() {
        // Return an empty string if the component is not activated.
        if (this.activation !== activationState.On) {
            return html``;
        }
        return html`
        <div>
            <span @click=${this.createReport}>${brw.i18n.getMessage("buttonCreateReport")}</span>
        </div>
      `;
    }
}
// Define a custom element for the component so that it can be used in the HTML DOM.
customElements.define("report-button", ReportButton);

/**
 * Lit component for the list of the detected patterns in the popup.
 * @extends LitElement
 */
export class FoundPatternsList extends LitElement {
    // Reactive properties
    static properties = {
        // Variable for the activation state of the component.
        activation: { type: Number },
        // Variable for the results of the pattern detection from the content script.
        results: { type: Object }
    };

    // CSS styles for the HTML elements in the component.
    static styles = [
        sharedStyles,
        patternsListStyles,
        patternLinkStyles
    ];

    /**
     * Render the HTML of the component.
     * @returns {html} HTML of the component
     */
    render() {
        // Return an empty string if the component is not activated.
        if (this.activation !== activationState.On) {
            return html``;
        }
        return html`
        <div>
            <h2>${brw.i18n.getMessage("headingFoundPatterns")}</h2>
            <h2 style="color: ${this.results.countVisible ? "red" : "green"}">${this.results.countVisible}</h2>
            <ul>
                ${this.results.patterns?.map((pattern) => {
            let currentPatternInfo = constants.patternConfig.patterns.find(p => p.name === pattern.name);
            if (pattern.elementsVisible.length === 0) {
                return html``;
            }
            return html`
                    <li title="${currentPatternInfo.info}">
                        <a href="${currentPatternInfo.infoUrl}" target="_blank">${pattern.name}</a>: ${pattern.elementsVisible.length}
                    </li>`;
        })}
            </ul>
        </div>
      `;
    }
}
// Define a custom element for the component so that it can be used in the HTML DOM.
customElements.define("found-patterns-list", FoundPatternsList);

/**
 * Lit component for the buttons used to show individual found patterns on the web page.
 * @extends LitElement
 */
export class ShowPatternButtons extends LitElement {
    // Reactive properties
    static properties = {
        // Variable for the activation state of the component.
        activation: { type: Number },
        // Variable for the results of the pattern detection from the content script.
        results: { type: Object },
        // Variable for the pattern highlighter ID of the currently selected pattern.
        // A "<frameId>:<phid>" string (see mergeFrameResults() above), not
        // a plain number — phids are only unique within one frame.
        _currentPatternId: { type: String, state: true },
        // Variable for the list of visible detected patterns.
        _visiblePatterns: { type: Array, state: true }
    };

    // CSS styles for the HTML elements in the component.
    static styles = [
        sharedStyles,
        patternLinkStyles,
        css`
            .button {
                font-size: large;
                cursor: pointer;
                user-select: none;
            }

            span {
                display: inline-block;
                text-align: center;
            }

            span:not(.button) {
                width: 110px;
                margin: 0 15px;
            }
        `
    ];

    /**
     * Function to extract only the visible elements from the `results` dictionary.
     */
    extractVisiblePatterns() {
        // Initialize the variable with an empty array.
        this._visiblePatterns = [];
        // Check if patterns were detected.
        if (this.results.patterns) {
            // Iterate through all detected patterns.
            for (const pattern of this.results.patterns) {
                // Check if there are visible elements for this pattern.
                if (pattern.elementsVisible.length > 0) {
                    // Iterate through all visible elements.
                    for (const elem of pattern.elementsVisible) {
                        // Add the id of the element and the name of the pattern to the visible patterns.
                        this._visiblePatterns.push({ "phid": elem, "patternName": pattern.name });
                    }
                }
            }
        }
    }

    /**
     * Get the index of an element in the `_visiblePatterns` array by its pattern highlighter ID.
     * @param {string} phid The "<frameId>:<phid>" composite pattern highlighter ID.
     * @returns {number|-1} The index of the element with the `phid` in the `_visiblePatterns` array
     * or `-1` if the element is not in the array.
     */
    getIndexOfPatternId(phid) {
        // Create an array of IDs from the `_visiblePatterns` and get the index of the passed `phid`.
        return this._visiblePatterns.map(pattern => pattern.phid).indexOf(phid);
    }

    /**
     * Show the next or previous pattern element on the website.
     * @param {number} step `x` for the next pattern or `-x` for the previous pattern.
     */
    async showPattern(step) {
        /**
         * Index of the pattern element to be shown.
         */
        let idx;
        // If there was no pattern shown before, the index must be set to the first or last element of the array.
        if (!this._currentPatternId) {
            if (step > 0) {
                // If one of the next elements should be shown,
                // set the index to `0`.
                idx = 0;
            } else {
                // If one of the previous elements should be shown,
                // set the index to the last element of the array.
                idx = this._visiblePatterns.length - 1;
            }
        } else {
            // If an element has already been shown, use its index as a starting point.
            idx = this.getIndexOfPatternId(this._currentPatternId);
            if (idx === -1) {
                // If the element is no longer present in the array, set the index to `0`.
                idx = 0;
            } else {
                // Add the passed `step` parameter to the index.
                idx += step;
            }
        }
        if (idx >= this._visiblePatterns.length) {
            // If the new index is greater/equal than the number of elements in the array,
            // set it to `0`.
            idx = 0;
        } else if (idx < 0) {
            // If the new index is smaller than 0,
            // set it to the index of the last element of the array.
            idx = this._visiblePatterns.length - 1;
        }
        // Set the ID of the currently shown element to the ID of the element at the new index.
        this._currentPatternId = this._visiblePatterns[idx].phid;
        // Decode the "<frameId>:<phid>" composite (see mergeFrameResults())
        // and target that specific frame — required once results can come
        // from an iframe, not just the main frame.
        const [frameIdStr, rawPhid] = String(this._currentPatternId).split(":");
        await brw.tabs.sendMessage(
            (await getCurrentTab()).id,
            { "showElement": Number(rawPhid) },
            { frameId: Number(frameIdStr) }
        );
    }

    /**
     * Function to show the next pattern element.
     * Used as a click event handler.
     * @param {Event} event
     */
    async showNextPattern(event) {
        await this.showPattern(1);
    }

    /**
     * Function to show the previous pattern element.
     * Used as a click event handler.
     * @param {Event} event
     */
    async showPreviousPattern(event) {
        await this.showPattern(-1);
    }

    /**
     * Function to generate the HTML text for the currently shown pattern.
     * @returns {html} HTML of the text for the currently shown pattern element
     */
    getCurrentPatternText() {
        // Only generate a text when a pattern element is shown.
        if (this._currentPatternId) {
            // Get the index of the current pattern element in the array.
            let idx = this.getIndexOfPatternId(this._currentPatternId);
            // Only generate a text when the element is still present in the array.
            if (idx !== -1) {
                // Get information about the pattern type from the configuration constant of the extension.
                let currentPatternInfo = constants.patternConfig.patterns.find(p => p.name === this._visiblePatterns[idx].patternName);
                // Generate the HTML text.
                return html`
                    <h3 title="${currentPatternInfo.info}">
                        <a href="${currentPatternInfo.infoUrl}" target="_blank">${this._visiblePatterns[idx].patternName}</a>
                    </h3>`;
            }
        }
        return html``;
    }

    /**
     * Function to generate the HTML of the number of the currently shown pattern element
     * @returns {html} HTML of the number (`index + 1`) of the currently shown pattern element
     */
    getCurrentPatternNumber() {
        // Only generate a text when a pattern element is shown.
        if (this._currentPatternId) {
            // Get the index of the current pattern element in the array.
            let idx = this.getIndexOfPatternId(this._currentPatternId);
            // Only generate a text when the element is still present in the array.
            if (idx !== -1) {
                // Generate the HTML text with the number (`index + 1`).
                return `${idx + 1}`;
            }
        }
        return "-";
    }

    /**
     * From the Lit documentation (https://lit.dev/docs/components/lifecycle/):
     * "Called before `update()` to compute values needed during the update.".
     * Used here to react to changes in the `results` before the component is rendered.
     * @param {Map} changedProperties
     */
    willUpdate(changedProperties) {
        // Extract the visible elements from the `results`, if the `results` have changed.
        if (changedProperties.has("results")) {
            this.extractVisiblePatterns();
        }
    }

    /**
     * Render the HTML of the component.
     * @returns {html} HTML of the component
     */
    render() {
        // Return an empty string if the component is not activated or if no patterns were detected.
        if (this.activation !== activationState.On || this.results.countVisible === 0) {
            return html``;
        }

        return html`
        <div>
            <h2>${brw.i18n.getMessage("headingShowPattern")}</h2>
            <span class="button" @click=${this.showPreviousPattern}>⏮️</span>
            <span>${brw.i18n.getMessage("showPatternState", [this.getCurrentPatternNumber(), this.results.countVisible.toString()])}</span>
            <span class="button" @click=${this.showNextPattern}>⏭️</span>
            ${this.getCurrentPatternText()}
        </div>
      `;
    }
}
// Define a custom element for the component so that it can be used in the HTML DOM.
customElements.define("show-pattern-button", ShowPatternButtons);

/**
 * Lit component for the list of all supported patterns in the popup.
 * @extends LitElement
 */
export class SupportedPatternsList extends LitElement {
    // CSS styles for the HTML elements in the component.
    static styles = [
        sharedStyles,
        patternsListStyles,
        patternLinkStyles,
        css`
            div {
                margin: 2.5em 0 1em;
            }
        `
    ];

    /**
     * Render the HTML of the component.
     * @returns {html} HTML of the component
     */
    render() {
        return html`
        <div>
            <h2>${brw.i18n.getMessage("headingSupportedPatterns")}</h2>
            <ul>
                ${constants.patternConfig.patterns.map((pattern) =>
            html`
                    <li title="${pattern.info}">
                        <a href="${pattern.infoUrl}" target="_blank">
                            ${pattern.name} (${pattern.languages.map(l => l.toUpperCase()).join(", ")})
                        </a>
                    </li>`
        )}
            </ul>
        </div>
      `;
    }
}
// Define a custom element for the component so that it can be used in the HTML DOM.
customElements.define("supported-patterns-list", SupportedPatternsList);

/**
 * Lit component for footer of the popup.
 * @extends LitElement
 */
export class PopupFooter extends LitElement {
    // CSS styles for the HTML elements in the component.
    static styles = [
        sharedStyles,
        css`
            div {
                margin-top: 2em;
            }
        `
    ];

    /**
     * Render the HTML of the component.
     * @returns {html} HTML of the component
     */
    render() {
        return html`
        <div>
            ${brw.i18n.getMessage("textMoreInformation")}: <a href="https://www.verbraucherzentrale.de/wissen/digitale-welt/onlinedienste/dark-patterns-so-wollen-websites-und-apps-sie-manipulieren-58082" target="_blank">verbraucherzentrale.de</a>.
        </div>
      `;
    }
}
// Define a custom element for the component so that it can be used in the HTML DOM.
customElements.define("popup-footer", PopupFooter);
