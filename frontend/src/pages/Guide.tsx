import { Link } from "react-router-dom";
import { ArrowRight, Crosshair, ScanSearch, Scale, FileText } from "lucide-react";
import SiteNav from "@/components/kali/SiteNav";
import SiteFooter from "@/components/kali/SiteFooter";
import PageTransition from "@/components/PageTransition";
import ScrollReveal from "@/components/ScrollReveal";

const steps = [
  {
    icon: ScanSearch,
    title: "1. Crawl",
    text: "An automated crawler visits target pages headless and captures the full interface — just like a real user would see it.",
  },
  {
    icon: Crosshair,
    title: "2. Detect",
    text: "Dark patterns are identified through a combination of visual heuristics and AI text classification.",
  },
  {
    icon: Scale,
    title: "3. Classify",
    text: "Every finding is automatically mapped to the relevant legal norm — UWG, BGB, DSGVO, DSA or PAngV.",
  },
  {
    icon: FileText,
    title: "4. Report",
    text: "A court-ready PDF report bundles the risk score, finding table, screenshots and timestamps as evidence.",
  },
];

const Guide = () => {
  return (
    <PageTransition>
      <div className="kali-light min-h-screen bg-background text-foreground font-sans flex flex-col">
        <SiteNav />

        <main className="flex-1">
          <section className="px-6 md:px-12 py-20 md:py-28">
            <div className="max-w-7xl mx-auto">
              <ScrollReveal className="text-center mb-14 md:mb-20">
                <p className="text-xs font-semibold tracking-[0.25em] uppercase text-primary mb-4">How Kali works</p>
                <h1 className="text-4xl md:text-6xl font-bold tracking-tight">
                  From suspicious page to <span className="font-serif italic font-medium text-primary">solid evidence</span>
                </h1>
                <p className="mt-5 max-w-2xl mx-auto text-base text-foreground/70 leading-relaxed">
                  Kali turns manipulative interface design into verifiable, legally classified evidence — in four steps.
                </p>
              </ScrollReveal>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-8">
                {steps.map((s) => (
                  <ScrollReveal key={s.title}>
                    <div className="bg-card rounded-3xl border border-border shadow-sm px-6 py-10 h-full">
                      <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-secondary mb-6">
                        <s.icon className="w-7 h-7 text-primary" strokeWidth={1.5} />
                      </div>
                      <h2 className="text-lg font-semibold mb-2">{s.title}</h2>
                      <p className="text-sm text-foreground/65 leading-relaxed">{s.text}</p>
                    </div>
                  </ScrollReveal>
                ))}
              </div>

              <ScrollReveal className="text-center mt-16">
                <Link
                  to="/dashboard"
                  className="inline-flex items-center justify-center gap-2 bg-foreground text-background px-7 py-3.5 rounded-full text-sm font-medium hover:bg-foreground/85 transition-colors"
                >
                  See it in the dashboard <ArrowRight className="w-4 h-4 text-primary" />
                </Link>
              </ScrollReveal>
            </div>
          </section>
        </main>

        <SiteFooter />
      </div>
    </PageTransition>
  );
};

export default Guide;
