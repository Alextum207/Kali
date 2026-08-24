import { useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  Briefcase,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Droplets,
  ExternalLink,
  FileText,
  Home,
  ListChecks,
  Radar,
  ReceiptText,
  Scale,
  Settings,
  SlidersHorizontal,
  Sparkles,
  Unlink,
  type LucideIcon,
} from "lucide-react";
import FireflyBadge from "@/components/FireflyBadge";
import logo from "@/assets/kali-firefly-logo.png";
import hotelRoom from "@/assets/hotel-room.jpg";

type Priority = "high" | "medium" | "low";
type Status = "New" | "In review" | "Assigned" | "Watching";

interface CaseItem {
  id: string;
  company: string;
  site: string;
  score: number;
  priority: Priority;
  pattern: string;
  legal: string[];
  evidence: number;
  status: Status;
  updated: string;
}

const patternIcons: Record<string, LucideIcon> = {
  "False Scarcity": Sparkles,
  "Hidden Costs": ReceiptText,
  "Hard to Cancel": Unlink,
  Preselection: ListChecks,
  "Drip Pricing": Droplets,
};

const patternDescriptions: Record<string, string> = {
  "False Scarcity":
    "The interface communicates limited availability in a way that may pressure the consumer to take a decision they would not have taken otherwise.",
  "Hidden Costs":
    "The interface reveals mandatory charges only late in the purchase process, so the initially advertised price is not attainable.",
  "Hard to Cancel":
    "The interface makes terminating a contract significantly harder than concluding it, obstructing the consumer's exit.",
  Preselection:
    "The interface pre-selects options — such as consent checkboxes or add-ons — so inaction leads to a choice the consumer may not intend.",
  "Drip Pricing":
    "The interface increases the total price step by step across the checkout flow, so the headline price is never the final price.",
};

const whyFlagged: Record<string, string[]> = {
  "False Scarcity": [
    "Scarcity claim with precise quantity (“2 rooms”)",
    "Displayed directly before purchase decision",
    "No evidence of actual limited availability",
    "Likely to induce hasty transactional decision",
  ],
  "Hidden Costs": [
    "Fees disclosed only in the final checkout step",
    "Total price not visible before purchase decision",
    "Cost breakdown hidden behind interaction",
    "Likely to mislead about the actual price",
  ],
  "Hard to Cancel": [
    "Cancellation requires significantly more steps than sign-up",
    "Cancellation option not visible in account settings",
    "No symmetric “cancel” path next to subscribe",
    "Likely to obstruct contract termination",
  ],
  Preselection: [
    "Consent checkboxes pre-ticked by default",
    "Additional services added without active choice",
    "User must actively deselect unwanted options",
    "Likely to invalidate consent under DSGVO Art. 7",
  ],
  "Drip Pricing": [
    "Price increases across checkout steps",
    "Mandatory fees excluded from headline price",
    "Advertised price not attainable",
    "Likely to mislead about the final price",
  ],
};

const legalDetails: Record<string, { label: string; match: string }[]> = {
  "False Scarcity": [
    { label: "§ 5 UWG – Misleading commercial practices", match: "Strong match" },
    { label: "Annex to § 3(3) UWG – Black List", match: "Context dependent" },
    { label: "DSA Art. 25 – Online interface design", match: "Possible" },
  ],
};

const matchLabels = ["Strong match", "Context dependent", "Possible"];

const cases: CaseItem[] = [
  { id: "travelnow", company: "TravelNow", site: "travelnow.com", score: 8.7, priority: "high", pattern: "False Scarcity", legal: ["§ 5 UWG", "DSA Art. 25"], evidence: 6, status: "New", updated: "May 18, 2026" },
  { id: "shoplux", company: "ShopLux", site: "shoplux.com", score: 8.2, priority: "high", pattern: "Hidden Costs", legal: ["§ 5 UWG"], evidence: 4, status: "In review", updated: "May 18, 2026" },
  { id: "streamit", company: "StreamIt", site: "streamit.com", score: 7.5, priority: "medium", pattern: "Hard to Cancel", legal: ["§ 5 UWG", "DSA Art. 25"], evidence: 8, status: "Assigned", updated: "May 17, 2026" },
  { id: "buymore", company: "BuyMore", site: "buymore.de", score: 6.1, priority: "medium", pattern: "Preselection", legal: ["DSGVO Art. 7", "§ 5 UWG"], evidence: 3, status: "Watching", updated: "May 17, 2026" },
  { id: "fitpro", company: "FitPro", site: "fitpro.com", score: 5.6, priority: "medium", pattern: "Drip Pricing", legal: ["§ 5 UWG"], evidence: 5, status: "New", updated: "May 16, 2026" },
  { id: "cloudplus", company: "CloudPlus", site: "cloudplus.com", score: 4.8, priority: "low", pattern: "Hidden Costs", legal: ["§ 5 UWG"], evidence: 3, status: "Watching", updated: "May 16, 2026" },
  { id: "musicday", company: "MusicDay", site: "musicday.com", score: 4.2, priority: "low", pattern: "Preselection", legal: ["DSGVO Art. 7"], evidence: 2, status: "Watching", updated: "May 15, 2026" },
];

const statusStyles: Record<Status, string> = {
  New: "bg-sky-100 text-sky-700",
  "In review": "bg-violet-100 text-violet-700",
  Assigned: "bg-amber-100 text-amber-700",
  Watching: "bg-emerald-100 text-emerald-700",
};

const priorityDots: Record<Priority, string> = {
  high: "bg-red-500",
  medium: "bg-amber-400",
  low: "bg-emerald-500",
};

const sidebarItems = [
  { icon: Home, label: "Overview" },
  { icon: Briefcase, label: "Cases", badge: "73", active: true },
  { icon: Radar, label: "Monitor" },
  { icon: Scale, label: "Legal basis" },
  { icon: FileText, label: "Reports" },
  { icon: Settings, label: "Settings" },
];

const filters = [
  { label: "All", count: 73, active: true },
  { label: "New", count: 31 },
  { label: "High priority", count: 18 },
  { label: "In review", count: 12 },
  { label: "Resolved", count: 152 },
];

const timeline = [
  { time: "20:48:12", label: "Page loaded" },
  { time: "20:48:14", label: "Scarcity message appeared" },
  { time: "20:48:18", label: "Screenshot captured" },
  { time: "20:48:20", label: "DOM & data preserved" },
];

const tabs = ["Overview", "Evidence", "Legal basis", "History", "Notes"];

const HotelMock = () => (
  <div className="bg-card border border-border rounded-2xl overflow-hidden">
    <img src={hotelRoom} alt="Captured booking interface showing a hotel room" className="w-full h-44 object-cover" width={512} height={640} loading="lazy" />
    <div className="p-4">
      <p className="font-semibold text-sm">Hotel Berlin Mitte</p>
      <p className="text-xs text-muted-foreground">Superior Room</p>
      <p className="mt-2 text-sm font-semibold">
        €159 <span className="font-normal text-muted-foreground">/ night</span>
      </p>
      <div className="mt-3 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
        <p className="text-xs font-medium text-red-600">⚡ Only 2 rooms left</p>
        <p className="text-xs font-medium text-red-600">at this price!</p>
      </div>
      <ul className="mt-3 space-y-1.5">
        {["Free cancellation", "Breakfast included", "Pay at the property"].map((item) => (
          <li key={item} className="flex items-center gap-2 text-xs text-foreground/70">
            <Check className="w-3.5 h-3.5 text-primary" /> {item}
          </li>
        ))}
      </ul>
      <button className="mt-4 w-full bg-foreground text-background text-xs font-medium rounded-lg py-2.5 hover:bg-foreground/85 transition-colors">
        Continue to payment
      </button>
    </div>
  </div>
);

const CaseDetail = ({
  item,
  onBack,
  onPrev,
  onNext,
  canPrev,
  canNext,
}: {
  item: CaseItem;
  onBack: () => void;
  onPrev: () => void;
  onNext: () => void;
  canPrev: boolean;
  canNext: boolean;
}) => {
  const PatternIcon = patternIcons[item.pattern] ?? Sparkles;
  const legal = legalDetails[item.pattern] ??
    item.legal.map((l, i) => ({ label: l, match: matchLabels[i % matchLabels.length] }));

  return (
    <div className="px-5 md:px-8 py-6">
      <button
        onClick={onBack}
        className="xl:hidden inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors mb-4"
      >
        <ArrowLeft className="w-4 h-4" /> Back to cases
      </button>

      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl md:text-2xl font-bold tracking-tight flex items-center gap-2">
            <Link to="/case-analysis" className="hover:underline">
              {item.company} – {item.pattern}
            </Link>
            <ExternalLink className="w-4 h-4 text-muted-foreground" />
          </h2>
          <p className="text-sm text-muted-foreground mt-1">{item.site} / checkout</p>
        </div>
        <div className="text-right shrink-0">
          {item.priority === "high" && (
            <span className="inline-block bg-red-100 text-red-600 text-[11px] font-medium rounded-full px-2.5 py-0.5 mb-1">
              High priority
            </span>
          )}
          <p className="text-3xl font-bold leading-none">
            {item.score.toFixed(1)} <span className="text-sm font-normal text-muted-foreground">/10</span>
          </p>
        </div>
      </div>

      <div className="mt-3">
        <Link
          to="/case-analysis"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline"
        >
          Open full case analysis <ArrowRight className="w-4 h-4" />
        </Link>
      </div>

      {/* Tabs */}
      <div className="flex items-start justify-between gap-3 mt-5 border-b border-border">
        <div className="flex gap-5 overflow-x-auto">
          {tabs.map((tab, i) => (
            <button
              key={tab}
              className={`pb-2.5 text-sm whitespace-nowrap transition-colors ${
                i === 0
                  ? "font-medium text-foreground border-b-2 border-primary -mb-px"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
        <div className="hidden md:flex flex-col shrink-0">
          <button
            onClick={onPrev}
            disabled={!canPrev}
            aria-label="Previous case"
            className="p-1 text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:hover:text-muted-foreground transition-colors"
          >
            <ChevronUp className="w-4 h-4" />
          </button>
          <button
            onClick={onNext}
            disabled={!canNext}
            aria-label="Next case"
            className="p-1 text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:hover:text-muted-foreground transition-colors"
          >
            <ChevronDown className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-5 mt-6">
        {/* Left column */}
        <div className="space-y-5">
          <div className="bg-card border border-border rounded-2xl p-5">
            <p className="text-xs font-semibold tracking-widest uppercase text-muted-foreground mb-3">Detected pattern</p>
            <div className="flex items-center gap-2.5 mb-3">
              <PatternIcon className="w-5 h-5 text-primary" />
              <p className="font-semibold">{item.pattern}</p>
            </div>
            <p className="text-sm text-foreground/70 leading-relaxed">{patternDescriptions[item.pattern]}</p>
            <p className="text-xs font-medium text-muted-foreground mt-4 mb-1.5">AI confidence</p>
            <div className="flex items-center gap-3">
              <div className="h-1.5 flex-1 rounded-full bg-secondary">
                <div className="h-full rounded-full bg-primary" style={{ width: "91%" }} />
              </div>
              <span className="text-sm font-semibold">91%</span>
            </div>
          </div>

          <div className="bg-card border border-border rounded-2xl p-5">
            <p className="text-xs font-semibold tracking-widest uppercase text-muted-foreground mb-3">Why Kali flagged it</p>
            <ul className="space-y-2.5">
              {(whyFlagged[item.pattern] ?? []).map((reason) => (
                <li key={reason} className="flex items-start gap-2.5 text-sm text-foreground/75">
                  <span className="mt-0.5 inline-flex items-center justify-center w-4 h-4 rounded-full bg-primary/15 shrink-0">
                    <Check className="w-3 h-3 text-primary" />
                  </span>
                  {reason}
                </li>
              ))}
            </ul>
          </div>

          <div className="bg-card border border-border rounded-2xl p-5">
            <p className="text-xs font-semibold tracking-widest uppercase text-muted-foreground mb-3">Possible legal basis</p>
            <ol className="space-y-3">
              {legal.map((l, i) => (
                <li key={l.label} className="flex items-start justify-between gap-3 text-sm">
                  <span className="text-foreground/80">
                    <span className="text-muted-foreground mr-2">{i + 1}</span>
                    {l.label}
                  </span>
                  <span className={`text-xs whitespace-nowrap ${i === 0 ? "text-primary font-medium" : "text-muted-foreground"}`}>
                    {l.match}
                  </span>
                </li>
              ))}
            </ol>
            <button className="mt-4 text-sm font-medium text-primary inline-flex items-center gap-1.5 hover:underline">
              View all legal bases <ArrowRight className="w-4 h-4" />
            </button>
          </div>

          <div className="bg-card border border-border rounded-2xl p-5">
            <p className="text-xs font-semibold tracking-widest uppercase text-muted-foreground mb-2">Human review</p>
            <p className="text-sm text-muted-foreground mb-4">This case has not been reviewed yet.</p>
            <div className="flex flex-col sm:flex-row gap-3">
              <button className="flex-1 bg-primary text-primary-foreground text-sm font-medium rounded-lg py-2.5 hover:opacity-90 transition-opacity">
                Confirm for review
              </button>
              <button className="flex-1 border border-border text-sm font-medium rounded-lg py-2.5 hover:bg-secondary transition-colors">
                Dismiss finding
              </button>
            </div>
          </div>
        </div>

        {/* Right column */}
        <div className="space-y-5">
          <div>
            <p className="text-xs font-semibold tracking-widest uppercase text-muted-foreground mb-3">Captured interface</p>
            <HotelMock />
            <p className="text-xs text-muted-foreground mt-2 text-center">Step 4 of 6 in checkout flow</p>
            <div className="flex justify-center gap-1.5 mt-1.5">
              {[0, 1, 2, 3].map((d) => (
                <span key={d} className={`w-1.5 h-1.5 rounded-full ${d === 0 ? "bg-primary" : "bg-border"}`} />
              ))}
            </div>
          </div>

          <div className="bg-card border border-border rounded-2xl p-5">
            <ul className="relative space-y-5">
              <div className="absolute left-[5px] top-2 bottom-2 w-px bg-border" />
              {timeline.map((e) => (
                <li key={e.time} className="relative pl-6">
                  <span className="absolute left-0 top-1 w-[11px] h-[11px] rounded-full bg-primary ring-4 ring-card" />
                  <p className="text-xs text-muted-foreground">{e.time}</p>
                  <p className="text-sm font-medium">{e.label}</p>
                </li>
              ))}
            </ul>
            <button className="mt-4 text-sm font-medium text-primary inline-flex items-center gap-1.5 hover:underline">
              View full timeline <ArrowRight className="w-4 h-4" />
            </button>
          </div>

          <div className="bg-card border border-border rounded-2xl p-5">
            <p className="text-xs font-semibold tracking-widest uppercase text-muted-foreground mb-3">
              Evidence ({item.evidence})
            </p>
            <div className="grid grid-cols-4 gap-2">
              {[0, 1, 2].map((i) => (
                <img
                  key={i}
                  src={hotelRoom}
                  alt={`Evidence capture ${i + 1}`}
                  className="w-full h-16 object-cover rounded-lg border border-border"
                  style={{ objectPosition: `${20 + i * 30}% ${30 + i * 20}%` }}
                  width={512}
                  height={640}
                  loading="lazy"
                />
              ))}
              <div className="w-full h-16 rounded-lg border border-border bg-secondary flex items-center justify-center text-sm font-medium text-muted-foreground">
                +{item.evidence - 3}
              </div>
            </div>
            <button className="mt-4 text-sm font-medium text-primary inline-flex items-center gap-1.5 hover:underline">
              View all evidence <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

const Dashboard = () => {
  const [selectedId, setSelectedId] = useState("travelnow");
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);
  const selectedIndex = cases.findIndex((c) => c.id === selectedId);
  const selected = cases[selectedIndex] ?? cases[0];

  const openCase = (id: string) => {
    setSelectedId(id);
    setMobileDetailOpen(true);
  };

  return (
    <div className="kali-light min-h-screen bg-background text-foreground font-sans flex">
      <FireflyBadge />
      {/* Sidebar */}
      <aside className="hidden lg:flex flex-col w-60 shrink-0 border-r border-border px-4 py-6 sticky top-0 h-screen">
        <Link to="/" className="flex items-center gap-2.5 px-2 mb-8">
          <img src={logo} alt="Kali firefly logo" className="w-8 h-8 object-contain" width={512} height={512} />
          <span className="text-lg font-bold tracking-[0.2em]">KALI</span>
        </Link>
        <nav className="space-y-1 flex-1">
          {sidebarItems.map((item) => (
            <button
              key={item.label}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                item.active ? "bg-secondary font-medium" : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground"
              }`}
            >
              <item.icon className="w-4.5 h-4.5 w-[18px] h-[18px]" strokeWidth={1.75} />
              {item.label}
              {item.badge && (
                <span className="ml-auto text-xs bg-primary/15 text-primary font-medium rounded-full px-2 py-0.5">
                  {item.badge}
                </span>
              )}
            </button>
          ))}
        </nav>
        <button className="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-secondary/60 transition-colors">
          <span className="w-8 h-8 rounded-full bg-secondary flex items-center justify-center text-xs font-semibold">AK</span>
          <span className="text-left">
            <span className="block text-sm font-medium">Anna K.</span>
            <span className="block text-xs text-muted-foreground">Consumer Protection Unit</span>
          </span>
          <ChevronDown className="w-4 h-4 text-muted-foreground ml-auto" />
        </button>
      </aside>

      {/* Main */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* Mobile top bar */}
        <div className="lg:hidden flex items-center justify-between px-4 py-3 border-b border-border bg-background sticky top-0 z-20">
          <Link to="/" className="flex items-center gap-2">
            <img src={logo} alt="Kali firefly logo" className="w-7 h-7 object-contain" width={512} height={512} />
            <span className="text-base font-bold tracking-[0.2em]">KALI</span>
          </Link>
          <Link to="/" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
            ← Landing page
          </Link>
        </div>

        <div className="flex flex-1 items-start">
          {/* Cases list */}
          <div className={`flex-1 min-w-0 px-5 md:px-8 py-6 ${mobileDetailOpen ? "hidden xl:block" : ""}`}>
            <h1 className="text-2xl md:text-3xl font-bold tracking-tight">Cases</h1>
            <p className="text-sm text-muted-foreground mt-1 mb-6">Investigation queue</p>

            {/* Filters */}
            <div className="flex flex-wrap items-center gap-2 mb-6">
              {filters.map((f) => (
                <button
                  key={f.label}
                  className={`px-3.5 py-1.5 rounded-full text-sm transition-colors ${
                    f.active
                      ? "bg-secondary font-medium"
                      : "border border-border text-muted-foreground hover:text-foreground hover:bg-secondary/60"
                  }`}
                >
                  {f.label} <span className="ml-1 text-xs text-muted-foreground">{f.count}</span>
                </button>
              ))}
              <button className="px-3.5 py-1.5 rounded-full text-sm border border-border text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5">
                <SlidersHorizontal className="w-3.5 h-3.5" /> Filters
              </button>
            </div>

            {/* Desktop table header */}
            <div
              className="hidden md:grid gap-4 px-4 py-2.5 text-[11px] font-semibold tracking-wider uppercase text-muted-foreground"
              style={{ gridTemplateColumns: "28px 52px 1.3fr 1.1fr 1.1fr 64px 96px 100px" }}
            >
              <span>Priority</span>
              <span>Score</span>
              <span>Company / Website</span>
              <span>Pattern</span>
              <span>Possible legal basis</span>
              <span>Evidence</span>
              <span>Status</span>
              <span>Updated</span>
            </div>

            {/* Rows */}
            <div className="space-y-1">
              {cases.map((c) => {
                const PatternIcon = patternIcons[c.pattern] ?? Sparkles;
                const isSelected = c.id === selectedId;
                return (
                  <button
                    key={c.id}
                    onClick={() => openCase(c.id)}
                    className={`w-full text-left rounded-xl px-4 py-3.5 transition-colors ${
                      isSelected ? "bg-secondary" : "hover:bg-secondary/50"
                    }`}
                  >
                    {/* Desktop row */}
                    <div
                      className="hidden md:grid gap-4 items-center"
                      style={{ gridTemplateColumns: "28px 52px 1.3fr 1.1fr 1.1fr 64px 96px 100px" }}
                    >
                      <span className={`w-2.5 h-2.5 rounded-full ${priorityDots[c.priority]}`} />
                      <span className="text-sm font-bold">{c.score.toFixed(1)}</span>
                      <span>
                        <span className="block text-sm font-semibold">{c.company}</span>
                        <span className="block text-xs text-muted-foreground">{c.site}</span>
                      </span>
                      <span className="flex items-center gap-2 text-sm text-foreground/80">
                        <PatternIcon className="w-4 h-4 text-muted-foreground" /> {c.pattern}
                      </span>
                      <span className="text-xs text-foreground/70 leading-relaxed">
                        {c.legal.map((l) => (
                          <span key={l} className="block">{l}</span>
                        ))}
                      </span>
                      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                        <FileText className="w-3.5 h-3.5" /> {c.evidence}
                      </span>
                      <span>
                        <span className={`inline-block text-xs font-medium rounded-full px-2.5 py-1 ${statusStyles[c.status]}`}>
                          {c.status}
                        </span>
                      </span>
                      <span className="text-xs text-muted-foreground">{c.updated}</span>
                    </div>

                    {/* Mobile row */}
                    <div className="md:hidden flex items-center gap-3">
                      <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${priorityDots[c.priority]}`} />
                      <span className="text-sm font-bold w-8">{c.score.toFixed(1)}</span>
                      <span className="flex-1 min-w-0">
                        <span className="block text-sm font-semibold truncate">{c.company}</span>
                        <span className="block text-xs text-muted-foreground truncate">{c.pattern}</span>
                      </span>
                      <span className={`inline-block text-[11px] font-medium rounded-full px-2 py-0.5 ${statusStyles[c.status]}`}>
                        {c.status}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>

            {/* Pagination */}
            <div className="flex items-center justify-between mt-6 text-sm text-muted-foreground">
              <span className="text-xs">1–7 of 73 cases</span>
              <div className="flex items-center gap-1">
                <button className="w-8 h-8 rounded-full flex items-center justify-center hover:bg-secondary transition-colors">
                  <ChevronLeft className="w-4 h-4" />
                </button>
                {[1, 2, 3].map((p) => (
                  <button
                    key={p}
                    className={`w-8 h-8 rounded-full text-xs flex items-center justify-center transition-colors ${
                      p === 1 ? "bg-secondary font-medium" : "hover:bg-secondary/60"
                    }`}
                  >
                    {p}
                  </button>
                ))}
                <span className="px-1">…</span>
                <button className="w-8 h-8 rounded-full text-xs flex items-center justify-center hover:bg-secondary/60 transition-colors">
                  11
                </button>
                <button className="w-8 h-8 rounded-full flex items-center justify-center hover:bg-secondary transition-colors">
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>

          {/* Detail pane */}
          <div
            className={`${
              mobileDetailOpen ? "block" : "hidden"
            } xl:block w-full xl:w-[600px] xl:shrink-0 border-l border-border bg-background/60`}
          >
            <CaseDetail
              item={selected}
              onBack={() => setMobileDetailOpen(false)}
              onPrev={() => setSelectedId(cases[selectedIndex - 1].id)}
              onNext={() => setSelectedId(cases[selectedIndex + 1].id)}
              canPrev={selectedIndex > 0}
              canNext={selectedIndex < cases.length - 1}
            />
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
