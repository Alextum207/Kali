import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, ExternalLink, Sun, ArrowRight } from "lucide-react";
import PageTransition from "@/components/PageTransition";
import FireflyBadge from "@/components/FireflyBadge";
import logo from "@/assets/kali-firefly-logo.png";
import { API_BASE_URL, getScan, postScan, type Finding, type Scan } from "@/lib/api";

const legalBases = [
  { n: 1, label: "§ 5 UWG – Misleading commercial practices", match: "Strong match" },
  { n: 2, label: "Annex to § 3(3) UWG – Black List", match: "Context dependent" },
  { n: 3, label: "DSA Art. 25 – Online interface design", match: "Possible" },
];

const tabs = ["Overview", "Evidence", "Legal basis", "History", "Notes"];

// Kali doesn't stream real progress from the crawler, so this narrates what
// a scan is doing in roughly the order it happens, cycling until it's done.
const scanSteps = [
  "Opening the page in a headless browser…",
  "Handling cookie banners and consent walls…",
  "Crawling checkout, account, and product pages…",
  "Comparing button colors, sizes, and contrast…",
  "Scanning page text for urgency, scarcity, and social-proof language…",
  "Checking pricing tables for decoy patterns…",
  "Capturing screenshots and DOM snapshots as evidence…",
  "Mapping findings to UWG, BGB, DSA, and DSGVO…",
  "Almost there — compiling the case file…",
];

const CaseAnalysis = () => {
  const [url, setUrl] = useState("");
  const [maxPages, setMaxPages] = useState(5);
  const [scanId, setScanId] = useState<number | null>(null);
  const [scan, setScan] = useState<Scan | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [status, setStatus] = useState<"idle" | "scanning" | "done" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [stepIndex, setStepIndex] = useState(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (status !== "scanning") return;
    setStepIndex(0);
    const id = setInterval(() => {
      setStepIndex((i) => Math.min(i + 1, scanSteps.length - 1));
    }, 2800);
    return () => clearInterval(id);
  }, [status]);

  useEffect(() => {
    if (scanId === null) return;
    const poll = async () => {
      try {
        const result = await getScan(scanId);
        setScan(result.scan);
        setFindings(result.findings);
        if (result.scan.status !== "running") {
          setStatus(result.scan.status === "error" ? "error" : "done");
          if (pollRef.current) clearInterval(pollRef.current);
        }
      } catch (err) {
        setError((err as Error).message);
        setStatus("error");
        if (pollRef.current) clearInterval(pollRef.current);
      }
    };
    poll();
    pollRef.current = setInterval(poll, 2000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [scanId]);

  const startScan = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return;
    setError(null);
    setStatus("scanning");
    setScan(null);
    setFindings([]);
    try {
      const { scan_id } = await postScan(url.trim(), maxPages);
      setScanId(scan_id);
    } catch (err) {
      setError((err as Error).message);
      setStatus("error");
    }
  };

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

          {/* Scan input */}
          <form
            onSubmit={startScan}
            className="mt-6 bg-card rounded-2xl border border-border shadow-sm p-4 md:p-6 flex flex-col sm:flex-row gap-3"
          >
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com"
              className="flex-1 rounded-lg border border-border bg-background px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            />
            <input
              type="number"
              min={1}
              max={30}
              value={maxPages}
              onChange={(e) => setMaxPages(Number(e.target.value))}
              title="Max. Seitenzahl"
              className="w-20 rounded-lg border border-border bg-background px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            />
            <button
              type="submit"
              disabled={status === "scanning"}
              className="px-6 py-2.5 rounded-lg bg-primary text-primary-foreground text-sm font-semibold hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              {status === "scanning" ? "Scanning…" : "Scan"}
            </button>
          </form>

          {status === "error" && (
            <p className="mt-4 text-sm text-destructive">{error ?? "Scan failed."}</p>
          )}

          {status === "idle" && (
            <p className="mt-8 text-sm text-foreground/60">Enter a URL above to run a scan.</p>
          )}

          {status === "scanning" && !scan && (
            <div className="mt-8 bg-card rounded-2xl border border-border shadow-sm p-6 md:p-8">
              <p className="text-sm font-medium">{scanSteps[stepIndex]}</p>
              <div className="mt-4 h-1.5 rounded-full bg-secondary overflow-hidden relative">
                <div className="absolute inset-y-0 w-1/3 bg-primary rounded-full animate-loading-bar" />
              </div>
            </div>
          )}

          {scan && status !== "error" && (
            <>
              {/* Header */}
              <div className="mt-6 flex flex-col md:flex-row md:items-start md:justify-between gap-6">
                <div>
                  <h1 className="text-3xl md:text-4xl font-bold tracking-tight flex items-center gap-3">
                    {scan.url}
                    <a href={scan.url} target="_blank" rel="noreferrer">
                      <ExternalLink className="w-5 h-5 text-foreground/50" />
                    </a>
                  </h1>
                  <p className="mt-2 text-sm text-foreground/60">
                    {findings.length} finding{findings.length === 1 ? "" : "s"}
                  </p>
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
                      {scan.risk.level === "hoch"
                        ? "High priority"
                        : scan.risk.level === "mittel"
                        ? "Medium priority"
                        : "Low priority"}
                    </span>
                    <p className="text-4xl font-bold leading-none">
                      {(scan.risk.score * 10).toFixed(1)} <span className="text-base font-medium text-foreground/50">/10</span>
                    </p>
                  </div>
                </div>
              </div>

              {/* Tabs (visual only, no backend data behind the other tabs yet) */}
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

              {findings.length === 0 ? (
                <p className="mt-8 text-sm text-foreground/60">No dark patterns detected on this scan.</p>
              ) : (
                <div className="mt-8 space-y-6">
                  {findings.map((f) => (
                    <div key={f.id} className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                      {/* Detected pattern */}
                      <div className="bg-card rounded-2xl border border-border shadow-sm p-6 md:p-8">
                        <h2 className="text-sm font-semibold mb-5">Detected pattern</h2>
                        <div className="flex items-center gap-3 mb-4">
                          <Sun className="w-7 h-7 text-foreground/70" strokeWidth={1.5} />
                          <p className="text-lg font-semibold">{f.pattern_type}</p>
                        </div>
                        <p className="text-sm text-foreground/65 leading-relaxed">{f.page_url}</p>

                        <div className="mt-6">
                          <div className="flex items-center justify-between text-sm mb-2">
                            <span className="text-foreground/70">AI confidence</span>
                            <span className="font-semibold">{Math.round(f.confidence_score * 100)}%</span>
                          </div>
                          <div className="h-1.5 rounded-full bg-secondary overflow-hidden">
                            <div
                              className="h-full bg-primary rounded-full"
                              style={{ width: `${Math.round(f.confidence_score * 100)}%` }}
                            />
                          </div>
                        </div>

                        <div className="mt-8 pt-6 border-t border-border">
                          <h3 className="text-sm font-semibold mb-2">Possible legal basis</h3>
                          <p className="text-sm text-foreground/70">{f.target_norm}</p>
                        </div>
                      </div>

                      {/* Captured interface */}
                      {f.screenshot_url && (
                        <div className="bg-card rounded-2xl border border-border shadow-sm p-6 md:p-8">
                          <h2 className="text-sm font-semibold mb-5">Captured interface</h2>
                          <img
                            src={`${API_BASE_URL}${f.screenshot_url}`}
                            alt={`Screenshot evidence for ${f.pattern_type}`}
                            className="w-full rounded-xl border border-border object-cover"
                            loading="lazy"
                          />
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Legal basis reference (static UWG/DSA overview, not per-finding) */}
              <div className="mt-6 bg-card rounded-2xl border border-border shadow-sm p-6 md:p-8">
                <h2 className="text-sm font-semibold mb-5">Legal reference</h2>
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
            </>
          )}
        </div>
      </div>
    </PageTransition>
  );
};

export default CaseAnalysis;
