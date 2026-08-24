import { Link } from "react-router-dom";
import logo from "@/assets/kali-firefly-logo.png";

const SiteFooter = () => (
  <footer className="border-t border-border px-6 md:px-12 py-10">
    <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-6">
      <div className="flex items-center gap-2.5">
        <img src={logo} alt="Kali firefly logo" className="w-7 h-7 object-contain" width={512} height={512} loading="lazy" />
        <span className="text-sm font-bold tracking-[0.2em]">KALI</span>
      </div>
      <nav className="flex flex-wrap items-center justify-center gap-x-8 gap-y-2">
        <Link to="/about" className="text-sm text-foreground/60 hover:text-foreground transition-colors">About us</Link>
        <Link to="/pitch-deck" className="text-sm text-foreground/60 hover:text-foreground transition-colors">Pitch Deck</Link>
        <Link to="/guide" className="text-sm text-foreground/60 hover:text-foreground transition-colors">How Kali works</Link>
        <a
          href="https://github.com/Alextum207/Kali"
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm text-foreground/60 hover:text-foreground transition-colors"
        >
          GitHub
        </a>
      </nav>
      <p className="text-xs text-foreground/50">Kali — detect dark patterns, never get tricked again.</p>
    </div>
  </footer>
);

export default SiteFooter;
