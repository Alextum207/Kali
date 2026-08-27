(function installKaliCountdownClockShim() {
    "use strict";

    const framePrefix = "__kali_countdown_verify__";
    if (typeof window.name !== "string" || !window.name.startsWith(framePrefix)) {
        return;
    }

    const RealDate = window.Date;
    const realPerformanceNow = window.performance && typeof window.performance.now === "function"
        ? window.performance.now.bind(window.performance)
        : null;
    let offsetMs = 0;

    function shiftedNow() {
        return RealDate.now() + offsetMs;
    }

    function KaliDate(...args) {
        if (this instanceof KaliDate) {
            return args.length === 0 ? new RealDate(shiftedNow()) : new RealDate(...args);
        }
        return new RealDate(shiftedNow()).toString();
    }

    Object.setPrototypeOf(KaliDate, RealDate);
    KaliDate.prototype = RealDate.prototype;
    KaliDate.now = shiftedNow;
    KaliDate.parse = RealDate.parse;
    KaliDate.UTC = RealDate.UTC;

    Object.defineProperty(window, "Date", {
        configurable: true,
        writable: true,
        value: KaliDate,
    });

    if (realPerformanceNow) {
        try {
            Object.defineProperty(window.performance, "now", {
                configurable: true,
                value: function now() {
                    return realPerformanceNow() + offsetMs;
                },
            });
        } catch (e) {
            // Some pages/browsers expose performance.now as non-configurable.
        }
    }

    function advanceClock(event) {
        const requestedOffset = Number(event && event.detail && event.detail.offsetMs);
        if (Number.isFinite(requestedOffset) && requestedOffset > offsetMs) {
            offsetMs = requestedOffset;
        }
        window.dispatchEvent(new CustomEvent("kali-countdown-clock-advanced", {
            detail: { offsetMs },
        }));
    }

    window.addEventListener("kali-countdown-clock-advance", advanceClock);
    document.addEventListener("kali-countdown-clock-advance", advanceClock);
})();
