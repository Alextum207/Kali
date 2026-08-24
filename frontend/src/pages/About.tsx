import SiteNav from "@/components/kali/SiteNav";
import SiteFooter from "@/components/kali/SiteFooter";
import PageTransition from "@/components/PageTransition";
import ScrollReveal from "@/components/ScrollReveal";
import teamKarinia from "@/assets/team-karinia.jpeg.asset.json";
import teamIra from "@/assets/team-ira.jpeg.asset.json";
import teamAlexander from "@/assets/team-alexander.jpeg.asset.json";

const members = [
  {
    name: "Karinia Häberle Marbaniang",
    role: "Law | Ludwig Maximilian Universität München",
    image: teamKarinia.url,
    link: "https://www.linkedin.com/in/karinia-h%C3%A4berle-marbaniang-10b079365?utm_source=share_via&utm_content=profile&utm_medium=member_ios",
  },
  {
    name: "Ira Haltia",
    role: "Law | Ludwig Maximilian Universität München & University of Helsinki",
    image: teamIra.url,
    link: "https://www.linkedin.com/in/irahaltia?utm_source=share_via&utm_content=profile&utm_medium=member_ios",
  },
  {
    name: "Alexander Saadé",
    role: "Information Systems | Technical University of Munich",
    image: teamAlexander.url,
    link: "https://www.linkedin.com/in/alexander-saade-0971853b3?utm_source=share_via&utm_content=profile&utm_medium=member_ios",
  },
];

const About = () => {
  return (
    <PageTransition>
      <div className="kali-light min-h-screen bg-background text-foreground font-sans flex flex-col">
        <SiteNav />

        <main className="flex-1">
          <section className="px-6 md:px-12 py-20 md:py-28">
            <div className="max-w-7xl mx-auto">
              <ScrollReveal className="text-center mb-14 md:mb-20">
                <p className="text-xs font-semibold tracking-[0.25em] uppercase text-primary mb-4">About us</p>
                <h1 className="text-4xl md:text-6xl font-bold tracking-tight">
                  The team behind <span className="font-serif italic font-medium text-primary">Kali</span>
                </h1>
                <p className="mt-5 max-w-2xl mx-auto text-base text-foreground/70 leading-relaxed">
                  We are a team of law and information systems students building AI infrastructure that makes
                  manipulative design visible — and actionable.
                </p>
              </ScrollReveal>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-10 md:gap-8">
                {members.map((m) => (
                  <ScrollReveal key={m.name}>
                    <a
                      href={m.link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="group block text-center bg-card rounded-3xl border border-border shadow-sm px-6 py-10 hover:shadow-md transition-shadow"
                    >
                      <img
                        src={m.image}
                        alt={`Portrait of ${m.name}`}
                        className="w-36 h-36 md:w-44 md:h-44 rounded-full object-cover mx-auto mb-6 border-4 border-secondary group-hover:border-primary transition-colors"
                        loading="lazy"
                      />
                      <h2 className="text-lg font-semibold mb-2">{m.name}</h2>
                      <p className="text-sm text-foreground/60 leading-relaxed">{m.role}</p>
                    </a>
                  </ScrollReveal>
                ))}
              </div>
            </div>
          </section>
        </main>

        <SiteFooter />
      </div>
    </PageTransition>
  );
};

export default About;
