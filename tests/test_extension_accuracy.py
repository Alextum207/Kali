import pathlib
import subprocess


EXTENSION_CONSTANTS = (
    pathlib.Path(__file__).parent.parent
    / "vendor"
    / "pattern-highlighter"
    / "chrome"
    / "scripts"
    / "constants.js"
)


def test_extension_text_patterns_match_backend_precision_guards():
    script = r"""
        import assert from "node:assert/strict";
        import { pathToFileURL } from "node:url";

        globalThis.chrome = { i18n: { getMessage: (key) => key } };
        const { patternConfig } = await import(pathToFileURL(process.argv[1]).href);

        const pattern = (className) => patternConfig.patterns.find((p) => p.className === className);
        const node = (text) => ({ tagName: "DIV", innerText: text, hasAttribute: () => false });
        const anyMatch = (className, text) => pattern(className).detectionFunctions.some((fn) => fn(node(text), null));
        const anyChangedMatch = (className, oldText, newText) =>
            pattern(className).detectionFunctions.some((fn) => fn(node(newText), node(oldText)));

        assert.equal(
            anyMatch("scarcity", "Beispiel: Nur noch 2 verfügbar soll als Testdatenbeispiel isoliert werden."),
            false
        );
        assert.equal(anyMatch("scarcity", "Nur noch 3 Stück verfügbar"), true);
        assert.equal(anyMatch("scarcity", "4.6 Sterne 39 Verkauft von Kali Markt"), false);

        assert.equal(anyChangedMatch("countdown", "USB-C Ladegerät 43A 65W", "USB-C Ladegerät 42A 65W"), false);

        assert.equal(
            anyMatch("social-proof", "Example: 128 customers have also bought this item is only documentation."),
            false
        );
        assert.equal(anyMatch("social-proof", "128 Kunden haben auch gekauft"), true);

        assert.equal(
            anyMatch("forced-continuity", "Beispiel: Danach 10 Euro/Monat beschreibt nur das Pattern."),
            false
        );
        assert.equal(anyMatch("forced-continuity", "Danach 10 Euro/Monat."), true);

        const checkbox = ({ id, text, checked = false, parentText = "" }) => {
            let label;
            const parent = parentText ? {
                tagName: "DIV",
                id: "",
                className: "cookie-category",
                innerText: parentText,
                getAttribute: () => "",
                parentElement: null
            } : null;
            const node = {
                tagName: "INPUT",
                type: "checkbox",
                checked,
                id,
                name: "",
                className: "",
                getAttribute: () => "",
                closest: () => null,
                parentElement: parent,
                nextElementSibling: null,
                getRootNode: () => ({
                    querySelector: (selector) => selector === `label[for="${id}"]` ? label : null
                })
            };
            label = { innerText: text };
            return node;
        };
        const preTicked = pattern("pre-ticked-box");
        assert.equal(
            preTicked.detectionFunctions.some((fn) => fn(checkbox({
                id: "cookie-allow-necessary",
                text: "Technisch notwendig (nicht abwählbar)",
                checked: true
            }), null)),
            false
        );
        assert.equal(
            preTicked.detectionFunctions.some((fn) => fn(checkbox({
                id: "ot-group-id-C0001",
                text: "",
                checked: true,
                parentText: "Unbedingt erforderliche Cookies sind immer aktiv."
            }), null)),
            false
        );
        assert.equal(
            preTicked.detectionFunctions.some((fn) => fn(checkbox({
                id: "newsletter",
                text: "Newsletter und Angebote per E-Mail erhalten",
                checked: true
            }), null)),
            true
        );
        assert.equal(
            preTicked.detectionFunctions.some((fn) => fn(checkbox({
                id: "roi-app-slack",
                text: "Slack",
                checked: true
            }), null)),
            false
        );
        assert.equal(
            preTicked.detectionFunctions.some((fn) => fn(checkbox({
                id: "billing-cycle-toggle",
                text: "Jährlich zahlen",
                checked: true
            }), null)),
            false
        );

        const trick = pattern("trick-questions");
        const notes = checkbox({ id: "notes", text: "Map Notes" });
        const data = checkbox({ id: "data", text: "Map Data" });
        notes.nextElementSibling = data;
        assert.equal(trick.detectionFunctions.some((fn) => fn(notes, null)), false);

        const autoplay = pattern("autoplay");
        const decorativeVideo = {
            tagName: "VIDEO",
            className: "hds-video-background",
            hasAttribute: (name) => ["autoplay", "muted", "loop", "playsinline"].includes(name)
        };
        assert.equal(autoplay.detectionFunctions.some((fn) => fn(decorativeVideo, null)), false);

        // Regression: a large content block (an article, a whole chat
        // answer, ...) must never match just because some small, unrelated
        // substring buried far inside it happens to look like a scarcity
        // phrase — highlighting would then tag the ENTIRE block. Real bug
        // report: an entire Perplexity chat answer got labeled Scarcity
        // this way (mistakes/false scarcity 2.png).
        const longBlock =
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore. " +
            "3 Stück verfügbar buried deep inside an unrelated long paragraph that keeps going and going. " +
            "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.";
        assert.equal(anyMatch("scarcity", longBlock), false);
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, str(EXTENSION_CONSTANTS)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
