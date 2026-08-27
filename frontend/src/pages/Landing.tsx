import { useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  Play,
  Crosshair,
  ShieldCheck,
  Scale,
  TrendingUp,
  Landmark,
  Users,
  User,
  Lock,
  Globe,
  BadgeCheck,
  Menu,
  X,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import heroBg from "@/assets/kali-hero.jpg";
import logo from "@/assets/kali-firefly-logo.png";
import visionVideo from "@/assets/vision-scan.mp4.asset.json";
import vorgehenVideo from "@/assets/vorgehensweise-crawler.mp4.asset.json";
import { LayoutDashboard, FileSearch, FileText, MessageSquare } from "lucide-react";

const navLinks = [
  { label: "Platform", href: "#platform" },
  { label: "How Kali works", href: "/guide", internal: true },
  { label: "Technology", href: "https://github.com/Alextum207/Kali", external: true },
  { label: "Resources", href: "https://github.com/Alextum207/Kali/blob/master/README.md", external: true },
  { label: "About us", href: "/about", internal: true },
];

const features = [
  { icon: Crosshair, title: "Detect", text: "manipulative patterns" },
  { icon: ShieldCheck, title: "Preserve", text: "verifiable evidence" },
  { icon: Scale, title: "Legal basis", text: "mapped to relevant law" },
  { icon: TrendingUp, title: "Prioritise", text: "cases for impact" },
];

const audiences = [
  {
    icon: Landmark,
    title: "Public Authorities",
    text: "Scale market surveillance and focus limited resources on the cases that matter most.",
  },
  {
    icon: Users,
    title: "Consumer Protection Organisations",
    text: "Monitor digital markets, document recurring practices, and turn observations into actionable evidence.",
  },
  {
    icon: User,
    title: "Consumers",
    text: "Understand manipulative design and contribute to a fairer digital environment.",
  },
];

const trust = [
  { icon: Lock, label: "Privacy by design" },
  { icon: Globe, label: "EU & national law aligned" },
  { icon: BadgeCheck, label: "Evidence you can rely on" },
  { icon: Users, label: "Independent & impartial" },
];

const kaliFeatures = [
  {
    icon: LayoutDashboard,
    title: "Dashboard with risk overview",
    text: "All previous scans at a glance, with a risk badge per page.",
  },
  {
    icon: FileSearch,
    title: "Finding details per page",
    text: "Which manipulative patterns were found where — with filtering options.",
  },
  {
    icon: Scale,
    title: "Legal classification",
    text: "Every finding is automatically mapped to the relevant norm (UWG, BGB, DSGVO, DSA, PAngV).",
  },
  {
    icon: FileText,
    title: "Court-ready PDF report",
    text: "Download an evidence report with cover sheet, risk score and finding table — including screenshot and timestamp as proof.",
  },
  {
    icon: MessageSquare,
    title: "Chatbot (planned)",
    text: "Case workers can ask questions about a scan's findings via chat and get answers with sources and disclaimers — nothing is stored.",
  },
];

const NavLinkItem = ({ link, onClick, className }: { link: (typeof navLinks)[number]; onClick?: () => void; className?: string }) => {
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

const Landing = () => {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="kali-light min-h-screen bg-background text-foreground font-sans">
      {/* Navigation */}
      <header className="absolute top-0 left-0 right-0 z-50">
        <div className="max-w-7xl mx-auto px-6 md:px-12 py-5 flex items-center justify-between gap-6">
          <Link to="/" className="flex items-center gap-2.5">
            <img src={logo} alt="Kali firefly logo" className="w-9 h-9 object-contain" width={512} height={512} />
            <span className="text-xl font-bold tracking-[0.2em]">KALI</span>
          </Link>

          <nav className="hidden lg:flex items-center gap-8">
            {navLinks.map((link) => (
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
              {navLinks.map((link) => (
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

      {/* Hero */}
      <section className="relative min-h-[92vh] flex items-center overflow-hidden">
        <img
          src={heroBg}
          alt="A glowing firefly in flight over a soft ivory background"
          className="absolute inset-0 w-full h-full object-cover"
          width={1920}
          height={1080}
        />
        <div className="absolute inset-x-0 bottom-0 h-32 bg-gradient-to-b from-transparent to-background" />

        <div className="relative max-w-7xl mx-auto px-6 md:px-12 w-full pt-32 pb-20">
          <p className="text-xs md:text-sm font-semibold tracking-[0.25em] uppercase text-primary mb-6">
            AI Infrastructure for Consumer Protection
          </p>
          <h1 className="text-5xl md:text-7xl lg:text-8xl font-bold tracking-tight leading-[1.02]">
            Kali shines light
            <br />
            in the <span className="font-serif italic font-medium text-primary">dark.</span>
          </h1>
          <p className="mt-6 max-w-md text-base md:text-lg text-foreground/70 leading-relaxed">
            We detect potentially manipulative digital interfaces, preserve evidence, and help authorities act where it
            matters most.
          </p>
          <div className="mt-8 flex flex-col sm:flex-row gap-4">
            <Link
              to="/dashboard"
              className="inline-flex items-center justify-center gap-2 bg-foreground text-background px-7 py-3.5 rounded-full text-sm font-medium hover:bg-foreground/85 transition-colors"
            >
              Explore the platform <ArrowRight className="w-4 h-4 text-primary" />
            </Link>
            <a
              href="#platform"
              className="inline-flex items-center justify-center gap-2 border border-foreground/25 px-7 py-3.5 rounded-full text-sm font-medium hover:bg-foreground/5 transition-colors"
            >
              <Play className="w-4 h-4 text-primary" /> See how Kali works
            </a>
          </div>

          {/* Feature row */}
          <div id="platform" className="mt-20 md:mt-28 grid grid-cols-2 md:grid-cols-4 gap-y-8 md:divide-x md:divide-foreground/15 scroll-mt-24">
            {features.map((f) => (
              <div key={f.title} className="flex items-start gap-3 md:px-6 first:md:pl-0">
                <f.icon className="w-7 h-7 text-primary shrink-0" strokeWidth={1.5} />
                <div>
                  <p className="text-sm font-semibold">{f.title}</p>
                  <p className="text-sm text-foreground/60">{f.text}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Audiences */}
      <section id="audiences" className="px-6 md:px-12 pb-16 md:pb-24 scroll-mt-24">
        <div className="max-w-7xl mx-auto bg-card rounded-3xl border border-border shadow-sm px-6 md:px-12 py-10 md:py-14">
          <p className="text-xs font-semibold tracking-[0.25em] uppercase text-foreground/60 text-center mb-10 md:mb-14">
            Built for those who protect consumers
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-10 md:gap-8 md:divide-x md:divide-border">
            {audiences.map((a) => (
              <div key={a.title} className="flex md:flex-col items-start gap-4 md:px-8 first:md:pl-0">
                <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-secondary shrink-0">
                  <a.icon className="w-7 h-7 text-primary" strokeWidth={1.5} />
                </div>
                <div>
                  <h3 className="text-lg font-semibold mb-2">{a.title}</h3>
                  <p className="text-sm text-foreground/65 leading-relaxed">{a.text}</p>
                </div>
              </div>
            ))}
          </div>

          {/* Trust row */}
          <div className="mt-14 md:mt-20 pt-10 border-t border-border">
            <p className="text-xs font-semibold tracking-[0.25em] uppercase text-foreground/60 text-center mb-8">
              Trusted, transparent, and built for accountability
            </p>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
              {trust.map((t) => (
                <div key={t.label} className="flex items-center justify-center gap-2.5">
                  <t.icon className="w-5 h-5 text-primary shrink-0" strokeWidth={1.5} />
                  <span className="text-sm font-medium">{t.label}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Vision & Vorgehen */}
      <section className="px-6 md:px-12 pb-16 md:pb-24">
        <div className="max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-2 gap-8">
          <div className="bg-card rounded-3xl border border-border shadow-sm overflow-hidden">
            <video
              src={visionVideo.url}
              autoPlay
              muted
              loop
              playsInline
              className="w-full aspect-video object-cover"
            />
            <div className="px-6 md:px-10 py-8 md:py-10">
              <h2 className="font-serif italic text-3xl md:text-4xl font-medium text-primary mb-4">Vision</h2>
              <p className="text-sm md:text-base text-foreground/65 leading-relaxed">
                Kali macht manipulative Dark-Pattern-Designs auf Webseiten sichtbar und rechtlich einordenbar, damit
                Verbraucherzentralen und Aufsichtsbehörden systematisch und gerichtsfest gegen sie vorgehen können.
              </p>
            </div>
          </div>
          <div className="bg-card rounded-3xl border border-border shadow-sm overflow-hidden">
            <video
              src={vorgehenVideo.url}
              autoPlay
              muted
              loop
              playsInline
              className="w-full aspect-video object-cover"
            />
            <div className="px-6 md:px-10 py-8 md:py-10">
              <h2 className="font-serif italic text-3xl md:text-4xl font-medium text-primary mb-4">Vorgehen</h2>
              <p className="text-sm md:text-base text-foreground/65 leading-relaxed">
                Ein automatisierter Crawler durchsucht Zielseiten headless, erkennt Dark Patterns über eine Kombination
                aus visuellen Heuristiken und KI-Textklassifikation, ordnet jeden Fund der einschlägigen Rechtsnorm und
                bietet einen Report.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="px-6 md:px-12 pb-16 md:pb-24">
        <div className="max-w-7xl mx-auto bg-card rounded-3xl border border-border shadow-sm px-6 md:px-12 py-10 md:py-14">
          <p className="text-xs font-semibold tracking-[0.25em] uppercase text-foreground/60 text-center mb-10 md:mb-14">
            Features
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-10 md:gap-8">
            {kaliFeatures.slice(0, 3).map((f) => (
              <div key={f.title} className="text-center">
                <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-secondary mb-5">
                  <f.icon className="w-7 h-7 text-primary" strokeWidth={1.5} />
                </div>
                <h3 className="text-lg font-semibold mb-2">{f.title}</h3>
                <p className="text-sm text-foreground/65 leading-relaxed">{f.text}</p>
              </div>
            ))}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-10 md:gap-8 mt-10 md:mt-12 max-w-3xl mx-auto">
            {kaliFeatures.slice(3).map((f) => (
              <div key={f.title} className="text-center">
                <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-secondary mb-5">
                  <f.icon className="w-7 h-7 text-primary" strokeWidth={1.5} />
                </div>
                <h3 className="text-lg font-semibold mb-2">{f.title}</h3>
                <p className="text-sm text-foreground/65 leading-relaxed">{f.text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Footer */}
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
    </div>
  );
};

export default Landing;
