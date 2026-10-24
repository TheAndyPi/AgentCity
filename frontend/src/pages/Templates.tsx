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
import { pretty } from "../api/defaults";
import { withScenarioPreset } from "../api/templatePresets";
const icons = [Waves, Package, MessageCircle, PartyPopper, Landmark];
export default function Templates() {
  const { client } = useApp();
  const navigate = useNavigate();
  const r = useQuery(() => client.templates(), [client]);
  return (
    <Page
      title="Common simulations"
      description="Start from a prepared scenario. Its settings are filled in for you and can be changed before you create it."
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
                  navigate("/simulations/new", {
                    state: { config: withScenarioPreset(t) },
                  })
                }
              >
                <div className={`template-art template-${i}`}>
                  <Icon size={56} strokeWidth={0.8} />
                </div>
                <div className="template-body">
                  <span className="template-mode">{pretty(t.config.mode)}</span>
                  <h2>{t.title}</h2>
                  <p>{t.description}</p>
                  <span className="link-text">
                    Customize this simulation <ArrowRight size={15} />
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
