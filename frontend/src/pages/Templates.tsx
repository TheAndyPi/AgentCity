import { useNavigate } from "react-router-dom";
import {
  ArrowRight,
  Waves,
  Package,
  MessageCircle,
  PartyPopper,
  Landmark,
} from "lucide-react";
import { Page, Busy, ErrorBox } from "../components/ui";
import { useApp, useQuery } from "../state/app";
const icons = [Waves, Package, MessageCircle, PartyPopper, Landmark];
export default function Templates() {
  const { client } = useApp();
  const navigate = useNavigate();
  const r = useQuery(() => client.templates(), [client]);
  return (
    <Page
      eyebrow="A SPARK FOR YOUR NEXT EXPERIMENT"
      title="Start with a little what if."
      description="Familiar starting points. Unexpected stories. Make any of these worlds your own."
    >
      {r.error ? (
        <ErrorBox
          error={`${r.error} Server templates are currently unavailable.`}
          retry={r.reload}
        />
      ) : !r.data ? (
        <Busy />
      ) : (
        <div className="template-grid">
          {r.data.items.map((t, i) => {
            const Icon = icons[i % icons.length];
            return (
              <button
                className="template-card"
                key={t.id}
                onClick={() =>
                  navigate("/simulations/new", { state: { config: t.config } })
                }
              >
                <div className={`template-art template-${i}`}>
                  <Icon size={56} strokeWidth={0.8} />
                  <span>0{i + 1}</span>
                </div>
                <div className="template-body">
                  <span className="eyebrow">A COMMUNITY EXPERIMENT</span>
                  <h2>{t.title}</h2>
                  <p>{t.description}</p>
                  <span className="link-text">
                    Make this world yours <ArrowRight size={15} />
                  </span>
                </div>
              </button>
            );
          })}
          {r.data.items.length === 0 && (
            <p className="muted">
              No server templates are available yet. You can still create a
              custom simulation.
            </p>
          )}
        </div>
      )}
    </Page>
  );
}
