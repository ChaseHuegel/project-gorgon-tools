import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import Loot from "./Loot";

const orphaned = {
  id: 7,
  captured_at: 1700000000000,
  source: "Giant Bat",
  activity: "Looting",
  item: "Bat Guano",
  amount: 1,
  zone: "Old Graveyard",
  status: "Orphaned",
  lag_ms: 0,
  linked_via: "orphan",
  monster_name: null,
  monster_lag_ms: null,
  target_name: null,
  target_lag_ms: null,
  corroborated_by_search: false,
  note: null,
  overridden: false,
};

describe("LootPage", () => {
  it("applies an override to the visible row without a reload", async () => {
    vi.spyOn(api, "loot").mockResolvedValue([orphaned]);
    vi.spyOn(api, "overrideLoot").mockResolvedValue({ ...orphaned, status: "Linked", overridden: true });
    render(<Loot />);

    const fix = await screen.findByText("Fix");
    fireEvent.click(fix);

    const statusSelect = screen
      .getAllByRole("combobox")
      .find((el) => (el as HTMLSelectElement).value === "Orphaned") as HTMLSelectElement;
    fireEvent.change(statusSelect, { target: { value: "Linked" } });
    fireEvent.click(screen.getByText("Save"));

    await waitFor(() => expect(api.overrideLoot).toHaveBeenCalledWith(7, expect.anything()));
    expect(await screen.findByText(/overridden/)).toBeInTheDocument();
    expect(screen.getByText(/Linked/)).toBeInTheDocument();
  });
});