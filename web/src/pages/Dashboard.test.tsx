import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import Dashboard from "./Dashboard";

const distinct = {
  sources: ["Giant Bat", "Dire Wolf"],
  zones: ["Old Graveyard", "Fairy Glen"],
  items: ["Bat Guano", "Wolf Pelt", "Bat Wing", "Ground Twig"],
  activities: ["Looting"],
};

const rates = [
  { monster: "Giant Bat", item: "Bat Guano", drops: 1, quantity: 1, encounters: 3, drop_rate: 0.3333 },
];
const summary = [
  { zone: "Old Graveyard", monster: "Giant Bat", activity: "Looting", item: "Bat Guano", total_quantity: 1, drop_count: 1 },
];
const sources = [{ monster: "Giant Bat", drops: 2, quantity: 2, encounters: 3, drop_rate: 0.6667 }];
const zones = [{ zone: "Old Graveyard", drops: 4, sources: 2 }];
const items = [{ item: "Bat Guano", drops: 1, sources: 1 }];
const stats = {
  drops: 4,
  encounters: 3,
  quantity: 5,
  sources: 2,
  items: 4,
  zones: 2,
  linked: 4,
  orphaned: 0,
  newest_at: 1,
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/dashboard"]}>
      <Dashboard />
    </MemoryRouter>,
  );
}

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.spyOn(api, "distinct").mockResolvedValue(distinct);
    vi.spyOn(api, "dropRates").mockResolvedValue(rates);
    vi.spyOn(api, "summary").mockResolvedValue(summary);
    vi.spyOn(api, "analysisSources").mockResolvedValue(sources);
    vi.spyOn(api, "analysisZones").mockResolvedValue(zones);
    vi.spyOn(api, "analysisItems").mockResolvedValue(items);
    vi.spyOn(api, "stats").mockResolvedValue(stats);
  });

  it("renders the overview tab with KPI cards and charts", async () => {
    renderPage();
    expect(await screen.findByText("Drop-rate dashboard")).toBeInTheDocument();
    expect(await screen.findByText("Top drop-rate sources (by sample size)")).toBeInTheDocument();
    expect(screen.getByText("Drop share by zone")).toBeInTheDocument();
    expect(screen.getByText("Most-dropped items")).toBeInTheDocument();
    expect(screen.getByText("Drops")).toBeInTheDocument();
    expect(screen.getAllByText("4").length).toBeGreaterThan(0);
    expect(screen.getByText("Export analysis CSV")).toBeInTheDocument();
  });

  it("drills down into an item from the rates table", async () => {
    vi.spyOn(api, "itemDetail").mockResolvedValue({
      item: "Bat Guano",
      sources: rates,
      zones: [{ zone: "Old Graveyard", drops: 4 }],
    });
    renderPage();
    fireEvent.click(screen.getByText("Rates & summary"));
    expect(await screen.findByText("Drop rates by monster and item")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /Bat Guano/ })[0]);
    expect(await screen.findByText(/Item \/ drop: Bat Guano/)).toBeInTheDocument();
    expect(api.itemDetail).toHaveBeenCalledWith("Bat Guano", undefined);
  });

  it("searches and drills down into a source from the find tab", async () => {
    vi.spyOn(api, "search").mockResolvedValue({
      sources: [{ name: "Giant Bat", drops: 2, encounters: 3 }],
      items: [],
      activities: [],
    });
    vi.spyOn(api, "sourceDetail").mockResolvedValue({
      source: "Giant Bat",
      zones: [{ zone: "Old Graveyard", drops: 4 }],
      items: rates,
    });
    renderPage();
    fireEvent.click(screen.getByText("Find drops"));
    const input = await screen.findByRole("combobox", { name: "Search" });
    fireEvent.change(input, { target: { value: "Giant" } });
    const result = await screen.findByRole("button", { name: /Giant Bat/ });
    fireEvent.click(result);
    expect(await screen.findByText(/Source: Giant Bat/)).toBeInTheDocument();
    await waitFor(() => expect(api.sourceDetail).toHaveBeenCalledWith("Giant Bat", undefined));
  });

  it("keeps the page rendered after closing a drill-down", async () => {
    vi.spyOn(api, "search").mockResolvedValue({
      sources: [{ name: "Giant Bat", drops: 2, encounters: 3 }],
      items: [],
      activities: [],
    });
    vi.spyOn(api, "sourceDetail").mockResolvedValue({
      source: "Giant Bat",
      zones: [{ zone: "Old Graveyard", drops: 4 }],
      items: rates,
    });
    renderPage();
    fireEvent.click(screen.getByText("Find drops"));
    const input = await screen.findByRole("combobox", { name: "Search" });
    fireEvent.change(input, { target: { value: "Giant" } });
    fireEvent.click(await screen.findByRole("button", { name: /Giant Bat/ }));
    fireEvent.click(await screen.findByText("Close"));
    expect(screen.queryByText(/Source: Giant Bat/)).not.toBeInTheDocument();
    expect(screen.getByText("Drop-rate dashboard")).toBeInTheDocument();
  });
});