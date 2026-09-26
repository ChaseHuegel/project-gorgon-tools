import { Page } from "../components/Page";

export default function About() {
  return (
    <Page title="About this data">
      <p>
        This site publishes drop-rate data collected with the open-source <strong>gorgon-tracker</strong>{" "}
        tool. A local capture tool records Project Gorgon loot pickups, attributes them to the
        monsters that dropped them, and publishes the verified rows here.
      </p>
      <div style={{ ...panelStyle, marginTop: "1rem" }}>
        <h2 style={{ fontSize: "0.9rem", margin: "0 0 0.5rem" }}>Reading the numbers</h2>
        <ul style={{ margin: 0, paddingLeft: "1.25rem", lineHeight: 1.6 }}>
          <li>
            <strong>Encounters</strong> counts the distinct fights that produced drops for a monster.
          </li>
          <li>
            <strong>Drop rate</strong> is drops divided by encounters. Small samples are marked Low.
          </li>
          <li>A row linked via a corpse search is corroborated; a target-only link carries less certainty.</li>
        </ul>
      </div>
      <p style={{ color: "var(--muted)", fontSize: "0.85rem", marginTop: "1rem" }}>
        Data is published by its curator and may be incomplete or contain errors.
      </p>
    </Page>
  );
}

const panelStyle: React.CSSProperties = {
  background: "var(--panel)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  padding: "0.75rem 1rem",
};