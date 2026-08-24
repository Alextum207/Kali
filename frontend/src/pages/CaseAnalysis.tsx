import { Link } from "react-router-dom";
import {
  ArrowLeft,
  ExternalLink,
  Sun,
  Check,
  CheckCircle2,
  Flame,
  Tag,
  ArrowRight,
} from "lucide-react";
import PageTransition from "@/components/PageTransition";
import FireflyBadge from "@/components/FireflyBadge";
import hotelRoom from "@/assets/hotel-room.jpg";
import logo from "@/assets/kali-firefly-logo.png";

const tabs = ["Overview", "Evidence", "Legal basis", "History", "Notes"];

const flags = [
  'Scarcity claim with precise quantity ("2 rooms")',
  "Displayed directly before purchase decision",
  "No evidence of actual limited availability",
  "Likely to induce hasty transactional decision",
];

const legalBases = [
  { n: 1, label: "§ 5 UWG – Misleading commercial practices", match: "Strong match" },
  { n: 2, label: "Annex to § 3(3) UWG – Black List", match: "Context dependent" },
  { n: 3, label: "DSA Art. 25 – Online interface design", match: "Possible" },
];

const timeline = [
  { time: "20:48:12", label: "Page loaded" },
  { time: "20:48:14", label: "Scarcity message appeared" },
  { time: "20:48:18", label: "Screenshot captured" },
  { time: "20:48:20", label: "DOM & data preserved" },
];

const CaseAnalysis = () => {
  return (
    <PageTransition>
      <div className="kali-light min-h-screen bg-background text-foreground font-sans">
        <FireflyBadge />
        <div className="max-w-6xl mx-auto px-6 md:px-12 py-8 md:py-12">
          <Link
            to="/dashboard"
            className="inline-flex items-center gap-2 text-sm font-medium text-foreground/70 hover:text-foreground transition-colors"
          >
            <ArrowLeft className="w-4 h-4" /> Back to cases
          </Link>

          {/* Header */}
          <div className="mt-6 flex flex-col md:flex-row md:items-start md:justify-between gap-6">
            <div>
              <h1 className="text-3xl md:text-4xl font-bold tracking-tight flex items-center gap-3">
                TravelNow – False Scarcity
                <ExternalLink className="w-5 h-5 text-foreground/50" />
              </h1>
              <p className="mt-2 text-sm text-foreground/60">travelnow.com / checkout</p>
            </div>
            <div className="flex items-center gap-8 md:text-right">
              <img
                src={logo}
                alt="Kali firefly"
                className="hidden md:block w-16 h-16 object-contain"
                width={512}
                height={512}
              />
              <div>
                <span className="inline-block text-xs font-semibold px-3 py-1 rounded-full bg-destructive/10 text-destructive mb-2">
                  High priority
                </span>
                <p className="text-4xl font-bold leading-none">
                  8.7 <span className="text-base font-medium text-foreground/50">/10</span>
                </p>
              </div>
            </div>
          </div>

          {/* Tabs */}
          <div className="mt-8 border-b border-border flex gap-8 overflow-x-auto">
            {tabs.map((t, i) => (
              <button
                key={t}
                className={`pb-3 text-sm font-medium whitespace-nowrap border-b-2 -mb-px transition-colors ${
                  i === 0
                    ? "border-primary text-foreground"
                    : "border-transparent text-foreground/60 hover:text-foreground"
                }`}
              >
                {t}
              </button>
            ))}
          </div>

          {/* Main grid */}
          <div className="mt-8 grid grid-cols-1 lg:grid-cols-[1fr_1fr_auto] gap-6">
            {/* Detected pattern */}
            <div className="bg-card rounded-2xl border border-border shadow-sm p-6 md:p-8">
              <h2 className="text-sm font-semibold mb-5">Detected pattern</h2>
              <div className="flex items-center gap-3 mb-4">
                <Sun className="w-7 h-7 text-foreground/70" strokeWidth={1.5} />
                <p className="text-lg font-semibold">False Scarcity</p>
              </div>
              <p className="text-sm text-foreground/65 leading-relaxed">
                The interface communicates limited availability in a way that may pressure the consumer to take a
                decision they would not have taken otherwise.
              </p>

              <div className="mt-6">
                <div className="flex items-center justify-between text-sm mb-2">
                  <span className="text-foreground/70">AI confidence</span>
                  <span className="font-semibold">91%</span>
                </div>
                <div className="h-1.5 rounded-full bg-secondary overflow-hidden">
                  <div className="h-full w-[91%] bg-primary rounded-full" />
                </div>
              </div>

              <div className="mt-8 pt-6 border-t border-border">
                <h3 className="text-sm font-semibold mb-4">Why Kali flagged it</h3>
                <ul className="space-y-3">
                  {flags.map((f) => (
                    <li key={f} className="flex items-start gap-3 text-sm text-foreground/70">
                      <CheckCircle2 className="w-4 h-4 text-primary shrink-0 mt-0.5" />
                      {f}
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            {/* Captured interface */}
            <div className="bg-card rounded-2xl border border-border shadow-sm p-6 md:p-8">
              <h2 className="text-sm font-semibold mb-5">Captured interface</h2>
              <div className="rounded-xl border border-border p-4 md:p-5 bg-background">
                <div className="flex gap-4">
                  <img
                    src={hotelRoom}
                    alt="Hotel room — captured checkout interface"
                    className="w-24 md:w-32 rounded-lg object-cover shrink-0"
                    loading="lazy"
                  />
                  <div className="min-w-0">
                    <p className="font-semibold">Hotel Berlin Mitte</p>
                    <p className="text-sm text-foreground/60">Superior Room</p>
                    <p className="mt-3 text-lg font-bold">
                      €159 <span className="text-sm font-medium text-foreground/60">/ night</span>
                    </p>
                    <div className="mt-2 inline-block rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2">
                      <p className="text-xs font-semibold text-destructive flex items-center gap-1.5">
                        <Flame className="w-3.5 h-3.5" /> Only 2 rooms left
                      </p>
                      <p className="text-xs font-semibold text-destructive flex items-center gap-1.5 mt-1">
                        <Tag className="w-3.5 h-3.5" /> at this price!
                      </p>
                    </div>
                  </div>
                </div>
                <ul className="mt-4 space-y-1.5">
                  {["Free cancellation", "Breakfast included", "Pay at the property"].map((x) => (
                    <li key={x} className="flex items-center gap-2 text-xs text-foreground/70">
                      <Check className="w-3.5 h-3.5 text-primary" /> {x}
                    </li>
                  ))}
                </ul>
                <button className="mt-4 w-full bg-foreground text-background text-sm font-medium rounded-lg py-2.5 hover:bg-foreground/85 transition-colors">
                  Continue to payment
                </button>
              </div>
              <p className="mt-4 text-center text-xs text-foreground/50">Step 4 of 6 in checkout flow</p>
              <div className="mt-2 flex justify-center gap-1.5">
                {[0, 1, 2, 3, 4].map((i) => (
                  <span
                    key={i}
                    className={`w-1.5 h-1.5 rounded-full ${i === 1 ? "bg-primary" : "bg-border"}`}
                  />
                ))}
              </div>
            </div>

            {/* Timeline */}
            <div className="lg:w-52">
              <ol className="relative border-l border-border pl-6 space-y-8">
                {timeline.map((t) => (
                  <li key={t.time} className="relative">
                    <span className="absolute -left-[29px] top-1 w-2.5 h-2.5 rounded-full bg-primary border-2 border-background" />
                    <p className="text-xs text-foreground/50">{t.time}</p>
                    <p className="text-sm font-medium">{t.label}</p>
                  </li>
                ))}
              </ol>
              <a
                href="#"
                className="mt-8 inline-flex items-center gap-2 text-sm font-medium text-primary hover:underline"
              >
                View full timeline <ArrowRight className="w-4 h-4" />
              </a>
            </div>
          </div>

          {/* Bottom grid */}
          <div className="mt-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Legal basis */}
            <div className="bg-card rounded-2xl border border-border shadow-sm p-6 md:p-8">
              <h2 className="text-sm font-semibold mb-5">Possible legal basis</h2>
              <ol className="divide-y divide-border">
                {legalBases.map((l) => (
                  <li key={l.n} className="py-3.5 flex items-start justify-between gap-4">
                    <div className="flex items-start gap-3">
                      <span className="text-xs font-semibold text-foreground/40 mt-0.5 w-4">{l.n}</span>
                      <span className="text-sm font-medium">{l.label}</span>
                    </div>
                    <span className="text-xs text-foreground/50 text-right shrink-0">{l.match}</span>
                  </li>
                ))}
              </ol>
              <a
                href="#"
                className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-primary hover:underline"
              >
                View all legal bases <ArrowRight className="w-4 h-4" />
              </a>
            </div>

            {/* Evidence */}
            <div className="bg-card rounded-2xl border border-border shadow-sm p-6 md:p-8">
              <h2 className="text-sm font-semibold mb-5">Evidence (6)</h2>
              <div className="grid grid-cols-5 gap-3">
                {[0, 1, 2, 3].map((i) => (
                  <div key={i} className="aspect-[3/4] rounded-lg border border-border overflow-hidden bg-secondary">
                    <img
                      src={hotelRoom}
                      alt={`Evidence capture ${i + 1}`}
                      className="w-full h-full object-cover"
                      loading="lazy"
                    />
                  </div>
                ))}
                <div className="aspect-[3/4] rounded-lg border border-border bg-secondary flex items-center justify-center">
                  <span className="text-sm font-semibold text-foreground/60">+3</span>
                </div>
              </div>
              <a
                href="#"
                className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-primary hover:underline"
              >
                View all evidence <ArrowRight className="w-4 h-4" />
              </a>
            </div>
          </div>

          {/* Human review */}
          <div className="mt-6 bg-card rounded-2xl border border-border shadow-sm p-6 md:p-8 flex flex-col md:flex-row md:items-center md:justify-between gap-5">
            <div>
              <h2 className="text-sm font-semibold mb-1">Human review</h2>
              <p className="text-sm text-foreground/60">This case has not been reviewed yet.</p>
            </div>
            <div className="flex flex-col sm:flex-row gap-3">
              <button className="px-6 py-2.5 rounded-lg bg-primary text-primary-foreground text-sm font-semibold hover:opacity-90 transition-opacity">
                Confirm for review
              </button>
              <button className="px-6 py-2.5 rounded-lg border border-border bg-background text-sm font-semibold hover:bg-secondary transition-colors">
                Dismiss finding
              </button>
            </div>
          </div>
        </div>
      </div>
    </PageTransition>
  );
};

export default CaseAnalysis;
