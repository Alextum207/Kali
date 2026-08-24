import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";
import SiteNav from "@/components/kali/SiteNav";
import SiteFooter from "@/components/kali/SiteFooter";
import PageTransition from "@/components/PageTransition";
import ScrollReveal from "@/components/ScrollReveal";

const slides = [
  {
    kicker: "The problem",
    title: "Dark patterns are everywhere — and hard to prove",
    text: "Manipulative interfaces nudge millions of consumers every day. Authorities lack the tools to detect, document and prosecute them at scale.",
  },
  {
    kicker: "The solution",
    title: "Kali detects, classifies and preserves evidence automatically",
    text: "A headless crawler combined with visual heuristics and AI text classification finds dark patterns and maps every finding to the relevant legal norm.",
  },
  {
    kicker: "The product",
    title: "A dashboard for case workers",
    text: "Risk overview across all scans, per-page finding details, legal classification and court-ready PDF reports — plus a planned chatbot for ad-hoc questions.",
  },
  {
    kicker: "The impact",
    title: "Systematic market surveillance for consumer protection",
    text: "Consumer organisations and authorities can focus limited resources on the cases that matter most — with evidence that holds up in court.",
  },
];

const PitchDeck = () => {
  return (
    <PageTransition>
      <div className="kali-light min-h-screen bg-background text-foreground font-sans flex flex-col">
        <SiteNav />

        <main className="flex-1">
          <section className="px-6 md:px-12 py-20 md:py-28">
            <div className="max-w-5xl mx-auto">
              <ScrollReveal className="text-center mb-14 md:mb-20">
                <p className="text-xs font-semibold tracking-[0.25em] uppercase text-primary mb-4">Pitch Deck</p>
                <h1 className="text-4xl md:text-6xl font-bold tracking-tight">
                  Kali in <span className="font-serif italic font-medium text-primary">four slides</span>
                </h1>
              </ScrollReveal>

              <div className="space-y-8">
                {slides.map((s) => (
                  <ScrollReveal key={s.kicker}>
                    <div className="bg-card rounded-3xl border border-border shadow-sm px-8 md:px-14 py-10 md:py-14 text-center">
                      <p className="text-xs font-semibold tracking-[0.25em] uppercase text-primary mb-4">{s.kicker}</p>
                      <h2 className="text-2xl md:text-4xl font-bold tracking-tight mb-4">{s.title}</h2>
                      <p className="text-sm md:text-base text-foreground/65 leading-relaxed max-w-2xl mx-auto">{s.text}</p>
                    </div>
                  </ScrollReveal>
                ))}
              </div>

              <ScrollReveal className="text-center mt-16">
                <Link
                  to="/dashboard"
                  className="inline-flex items-center justify-center gap-2 bg-foreground text-background px-7 py-3.5 rounded-full text-sm font-medium hover:bg-foreground/85 transition-colors"
                >
                  Explore the platform <ArrowRight className="w-4 h-4 text-primary" />
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

export default PitchDeck;
