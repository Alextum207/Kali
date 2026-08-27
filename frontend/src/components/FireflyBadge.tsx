import logo from "@/assets/kali-firefly-logo.png";

/** Floating brand watermark, fixed to the viewport corner — same firefly
 * used everywhere else in the app, just with a soft glow behind it. */
const FireflyBadge = () => (
  <div className="fixed bottom-6 right-6 z-30 pointer-events-none">
    <div className="relative w-14 h-14">
      <div className="absolute -inset-3.5 rounded-full bg-gradient-to-br from-primary/40 via-amber-200/40 to-transparent blur-xl" />
      <div className="relative w-14 h-14 rounded-full bg-card shadow-lg flex items-center justify-center">
        <img src={logo} alt="" className="w-8 h-8 object-contain" width={512} height={512} />
      </div>
    </div>
  </div>
);

export default FireflyBadge;
