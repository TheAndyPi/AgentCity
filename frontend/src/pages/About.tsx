import { Link } from "react-router-dom";
import {
  ArrowRight,
  BrainCircuit,
  MessagesSquare,
  Sparkles,
  GitBranch,
} from "lucide-react";
import { CityMark, Page } from "../components/ui";
export default function About() {
  return (
    <Page title="About AgentCity">
      <div className="about-hero">
        <CityMark className="about-mark" />
        <p>
          AgentCity is an interactive 3D society simulator where AI citizens
          make decisions, remember experiences, and influence the world around
          them.
        </p>
        <p>
          Explore a procedurally generated town, introduce your own scenarios
          such as floods, misinformation, or resource shortages, and observe
          how citizens respond based on their personalities, needs,
          relationships, and memories. Policy and misinformation labs let you
          test rules and rumors in the same way.
        </p>
        <Link to="/simulations/new" className="button primary">
          Build custom simulation
          <ArrowRight size={17} />
        </Link>
      </div>
      <section className="how-it-works">
        <h2>How it works</h2>
        <div>
          {[
            {
              icon: BrainCircuit,
              title: "Agent decisions",
              text: "Each citizen acts on what it can observe, what it remembers, and who it knows. Every decision is recorded with the evidence behind it.",
            },
            {
              icon: MessagesSquare,
              title: "Memory and relationships",
              text: "Conversations and shared experiences are stored as memories and shape relationships. Trust can differ in each direction.",
            },
            {
              icon: Sparkles,
              title: "Environment and events",
              text: "Describe any event. You preview what citizens will experience, server rules validate their actions, and the simulation records the consequences.",
            },
            {
              icon: GitBranch,
              title: "History and branches",
              text: "Every step is saved. Return to an earlier snapshot or branch from it to try a different outcome without losing the original.",
            },
          ].map(({ icon: Icon, title, text }) => (
            <article key={title}>
              <Icon size={26} />
              <h3>{title}</h3>
              <p>{text}</p>
            </article>
          ))}
        </div>
      </section>
      <div className="about-team">
        <div>
          <h2>The team</h2>
        </div>
        <div>
          <p>
            <strong>Jillian & Isabella</strong>
            <span>Frontend</span>
          </p>
          <p>
            <strong>Andrew & Anderson</strong>
            <span>Backend</span>
          </p>
        </div>
      </div>
      <p className="exploratory-note">
        AgentCity simulations are exploratory. They do not predict human
        behavior with scientific certainty.
      </p>
    </Page>
  );
}
