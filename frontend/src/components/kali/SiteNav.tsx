import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Menu, X } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import logo from "@/assets/kali-firefly-logo.png";

export const kaliNavLinks = [
  { label: "Platform", href: "/#platform" },
  { label: "How Kali works", href: "/guide", internal: true },
  { label: "Technology", href: "https://github.com/Alextum207/Kali", external: true },
  { label: "Resources", href: "https://github.com/Alextum207/Kali/blob/master/README.md", external: true },
  { label: "About us", href: "/about", internal: true },
];

export const NavLinkItem = ({
  link,
  onClick,
  className,
}: {
  link: (typeof kaliNavLinks)[number];
  onClick?: () => void;
  className?: string;
}) => {
  if (link.internal) {
    return (
      <Link to={link.href} onClick={onClick} className={className}>
        {link.label}
      </Link>
    );
  }
  if (link.external) {
    return (
      <a href={link.href} target="_blank" rel="noopener noreferrer" onClick={onClick} className={className}>
        {link.label}
      </a>
    );
  }
  return (
    <a href={link.href} onClick={onClick} className={className}>
      {link.label}
    </a>
  );
};

const SiteNav = () => {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <header className="sticky top-0 left-0 right-0 z-50 bg-background/90 backdrop-blur-sm border-b border-border">
      <div className="max-w-7xl mx-auto px-6 md:px-12 py-5 flex items-center justify-between gap-6">
        <Link to="/" className="flex items-center gap-2.5">
          <img src={logo} alt="Kali firefly logo" className="w-9 h-9 object-contain" width={512} height={512} />
          <span className="text-xl font-bold tracking-[0.2em]">KALI</span>
        </Link>

        <nav className="hidden lg:flex items-center gap-8">
          {kaliNavLinks.map((link) => (
            <NavLinkItem
              key={link.label}
              link={link}
              className="text-sm font-medium text-foreground/70 hover:text-foreground transition-colors"
            />
          ))}
        </nav>

        <div className="hidden lg:flex items-center gap-3">
          <Link
            to="/dashboard"
            className="px-5 py-2.5 text-sm font-medium border border-foreground/25 rounded-full hover:bg-foreground/5 transition-colors"
          >
            Log in
          </Link>
          <Link
            to="/dashboard"
            className="px-5 py-2.5 text-sm font-medium bg-foreground text-background rounded-full hover:bg-foreground/85 transition-colors inline-flex items-center gap-2"
          >
            Request a demo <ArrowRight className="w-4 h-4 text-primary" />
          </Link>
        </div>

        <button
          className="lg:hidden text-foreground"
          onClick={() => setMobileOpen(!mobileOpen)}
          aria-label="Toggle navigation menu"
        >
          {mobileOpen ? <X size={24} /> : <Menu size={24} />}
        </button>
      </div>

      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            className="lg:hidden bg-card border-t border-border px-6 py-6 space-y-4 overflow-hidden shadow-lg"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3, ease: "easeInOut" }}
          >
            {kaliNavLinks.map((link) => (
              <NavLinkItem
                key={link.label}
                link={link}
                onClick={() => setMobileOpen(false)}
                className="block text-sm font-medium text-foreground/70 hover:text-foreground transition-colors"
              />
            ))}
            <div className="flex flex-col gap-3 pt-2">
              <Link
                to="/dashboard"
                onClick={() => setMobileOpen(false)}
                className="px-5 py-2.5 text-sm font-medium border border-foreground/25 rounded-full text-center"
              >
                Log in
              </Link>
              <Link
                to="/dashboard"
                onClick={() => setMobileOpen(false)}
                className="px-5 py-2.5 text-sm font-medium bg-foreground text-background rounded-full text-center"
              >
                Request a demo
              </Link>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  );
};

export default SiteNav;
