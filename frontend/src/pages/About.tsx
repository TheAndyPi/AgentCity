import { Link } from "react-router-dom";
import {
  ArrowRight,
  BrainCircuit,
  MessagesSquare,
  Sparkles,
  GitBranch,
} from "lucide-react";
import { Page } from "../components/ui";
export default function About() {
  return (
    <Page
      eyebrow="SMALL WORLDS. BIG QUESTIONS."
      title="A city with a mind of its own."
      description="AgentCity is a place to ask what if, then watch the answers unfold."
    >
      <div className="about-hero">
        <span className="about-symbol">✳</span>
        <h2>
          People make a place.
          <br />
          <span>Possibility makes a city.</span>
        </h2>
        <p>
          Create a neighborhood of autonomous citizens with personalities,
          goals, memories, and relationships. Change their environment,
          introduce an event, and explore the choices that follow.
        </p>
        <Link to="/simulations/new" className="button primary">
          Create your first world
          <ArrowRight size={17} />
        </Link>
      </div>
      <section className="how-it-works">
        <div className="eyebrow">HOW IT WORKS</div>
        <h2>A living loop of choices and consequences.</h2>
        <div>
          {[
            {
              icon: BrainCircuit,
              title: "A perspective of their own",
              text: "Citizens act on what they can observe, what they remember, and who they know. Recorded decisions connect intention to evidence.",
            },
            {
              icon: MessagesSquare,
              title: "Connections that carry forward",
              text: "Conversations and shared experiences shape directed relationships. Trust can be different in each direction.",
            },
            {
              icon: Sparkles,
              title: "A change in the everyday",
              text: "Describe any event. Preview what citizens experience. Server rules validate actions, and committed state records the consequences.",
            },
            {
              icon: GitBranch,
              title: "Another way things could go",
              text: "Look back through recorded history. Branch from a saved point to try a new possibility while preserving the original story.",
            },
          ].map(({ icon: Icon, title, text }, i) => (
            <article key={title}>
              <span className="step-number">0{i + 1}</span>
              <Icon size={26} />
              <h3>{title}</h3>
              <p>{text}</p>
            </article>
          ))}
        </div>
      </section>
      <div className="about-team">
        <div>
          <div className="eyebrow">THE PEOPLE BEHIND THE POSSIBILITY</div>
          <h2>Built with curiosity.</h2>
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
