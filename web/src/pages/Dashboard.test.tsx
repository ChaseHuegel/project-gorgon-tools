import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.spyOn(api, "distinct").mockResolvedValue(distinct);
    vi.spyOn(api, "dropRates").mockResolvedValue(rates);
    vi.spyOn(api, "summary").mockResolvedValue(summary);
    vi.spyOn(api, "analysisSources").mockResolvedValue(sources);
    vi.spyOn(api, "analysisZones").mockResolvedValue(zones);
    vi.spyOn(api, "analysisItems").mockResolvedValue(items);
  });

  it("renders the analysis page with charts and tables", async () => {
    render(<Dashboard />);
    expect(await screen.findByText("Drop-rate dashboard")).toBeInTheDocument();
    expect(await screen.findByText("Total drops by source")).toBeInTheDocument();
    expect(screen.getByText("Drop share by zone")).toBeInTheDocument();
    expect(screen.getByText("Most-dropped items")).toBeInTheDocument();
    expect(await screen.findByRole("textbox", { name: "Search" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText("Bat Guano").length).toBeGreaterThan(0));
  });

  it("searches and drills down into a source", async () => {
    vi.spyOn(api, "search").mockResolvedValue({ sources: [{ name: "Giant Bat", drops: 2, encounters: 3 }], items: [], activities: [] });
    vi.spyOn(api, "sourceDetail").mockResolvedValue({
      source: "Giant Bat",
      zones: [{ zone: "Old Graveyard", drops: 4 }],
      items: rates,
    });
    render(<Dashboard />);
    const input = await screen.findByRole("textbox", { name: "Search" });
    fireEvent.change(input, { target: { value: "Giant" } });
    const result = await screen.findByRole("button", { name: /Giant Bat/ });
    fireEvent.click(result);
    expect(await screen.findByText(/Source: Giant Bat/)).toBeInTheDocument();
    await waitFor(() => expect(api.sourceDetail).toHaveBeenCalledWith("Giant Bat"));
  });

  it("keeps the page rendered after closing a drill-down", async () => {
    vi.spyOn(api, "search").mockResolvedValue({ sources: [{ name: "Giant Bat", drops: 2, encounters: 3 }], items: [], activities: [] });
    vi.spyOn(api, "sourceDetail").mockResolvedValue({
      source: "Giant Bat",
      zones: [{ zone: "Old Graveyard", drops: 4 }],
      items: rates,
    });
    render(<Dashboard />);
    const input = await screen.findByRole("textbox", { name: "Search" });
    fireEvent.change(input, { target: { value: "Giant" } });
    fireEvent.click(await screen.findByRole("button", { name: /Giant Bat/ }));
    fireEvent.click(await screen.findByText("Close"));
    expect(screen.queryByText(/Source: Giant Bat/)).not.toBeInTheDocument();
    expect(screen.getByText("Drop-rate dashboard")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Search" })).toBeInTheDocument();
  });
});