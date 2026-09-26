import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { LootRow } from "../api/types";
import LootPublic from "./LootPublic";

function makeRow(overrides: Partial<LootRow> = {}): LootRow {
  return {
    id: 7,
    captured_at: 1700000000000,
    source: "Giant Bat",
    activity: "Looting",
    item: "Bat Guano",
    amount: 1,
    zone: "Old Graveyard",
    status: "Linked",
    lag_ms: 0,
    linked_via: "monster",
    monster_name: null,
    monster_lag_ms: null,
    target_name: null,
    target_lag_ms: null,
    corroborated_by_search: false,
    note: null,
    overridden: false,
    ...overrides,
  };
}

describe("LootPublic", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders loot rows and filters by source", async () => {
    vi.spyOn(api, "loot").mockResolvedValue([
      makeRow(),
      makeRow({ id: 8, source: "Wolf", item: "Wolf Fang" }),
    ]);
    render(<LootPublic />);

    await screen.findByText("Bat Guano");
    expect(screen.getByText("Wolf Fang")).toBeInTheDocument();
    expect(screen.getByText(/2 row/)).toBeInTheDocument();

    fireEvent.change(screen.getByTitle("Source"), { target: { value: "Giant Bat" } });
    expect(screen.getByText(/1 row/)).toBeInTheDocument();
    expect(screen.queryByText("Wolf Fang")).not.toBeInTheDocument();
  });

  it("shows the empty state when nothing is recorded", async () => {
    vi.spyOn(api, "loot").mockResolvedValue([]);
    render(<LootPublic />);
    expect(await screen.findByText("No loot recorded yet.")).toBeInTheDocument();
    expect(screen.getByText("0 row(s)")).toBeInTheDocument();
  });
});