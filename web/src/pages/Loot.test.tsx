import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { LootRow, Status } from "../api/types";
import Loot from "./Loot";

function makeRow(overrides: Partial<LootRow> = {}): LootRow {
  return {
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
    ...overrides,
  };
}

const orphaned = makeRow();

function publishStatus(): Status {
  return {
    db_path: "/tmp/x.db",
    config_path: "/tmp/x.toml",
    config_db_path: "/tmp/x.db",
    sessions_total: 0,
    open_session_id: null,
    open_session_counts: null,
    daemon: { pid: null, running: false, pidfile: "" },
    warnings: [],
    publish: { configured: true, url: "https://loot.example.test" },
  };
}

describe("LootPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "status").mockResolvedValue(publishStatus());
  });

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

  it("deletes a single row after confirmation", async () => {
    let stored = [orphaned];
    vi.spyOn(api, "loot").mockImplementation(async () => stored);
    vi.spyOn(api, "deleteLootRows").mockImplementation(async (ids) => {
      stored = stored.filter((r) => !ids.includes(r.id));
      return { deleted: ids.length };
    });
    render(<Loot />);

    await screen.findByText("Bat Guano");
    const rowDelete = screen.getAllByRole("button", { name: "Delete" })[0];
    fireEvent.click(rowDelete);

    expect(screen.getByText("Delete loot row?")).toBeInTheDocument();
    const confirm = screen.getAllByRole("button", { name: "Delete" }).pop()!;
    fireEvent.click(confirm);

    await waitFor(() => expect(api.deleteLootRows).toHaveBeenCalledWith([7]));
    await waitFor(() => expect(screen.queryByText("Bat Guano")).not.toBeInTheDocument());
  });

  it("deletes multiple selected rows at once", async () => {
    const rows = [makeRow({ id: 7 }), makeRow({ id: 8, item: "Wolf Fang", source: "Wolf" })];
    let stored = rows;
    vi.spyOn(api, "loot").mockImplementation(async () => stored);
    vi.spyOn(api, "deleteLootRows").mockImplementation(async (ids) => {
      stored = stored.filter((r) => !ids.includes(r.id));
      return { deleted: ids.length };
    });
    render(<Loot />);

    await screen.findByText("Bat Guano");
    fireEvent.click(screen.getByLabelText("Select row 7"));
    fireEvent.click(screen.getByLabelText("Select row 8"));

    const bulk = screen.getByRole("button", { name: "Delete selected (2)" });
    fireEvent.click(bulk);
    expect(screen.getByText("Delete 2 loot rows?")).toBeInTheDocument();

    const confirm = screen.getAllByRole("button", { name: "Delete" }).pop()!;
    fireEvent.click(confirm);

    await waitFor(() => expect(api.deleteLootRows).toHaveBeenCalledWith([7, 8]));
    await waitFor(() => expect(screen.queryByText("Bat Guano")).not.toBeInTheDocument());
  });

  it("cancelling the dialog leaves the row untouched", async () => {
    vi.spyOn(api, "loot").mockResolvedValue([orphaned]);
    const del = vi.spyOn(api, "deleteLootRows").mockResolvedValue({ deleted: 1 });
    render(<Loot />);

    await screen.findByText("Bat Guano");
    fireEvent.click(screen.getAllByRole("button", { name: "Delete" })[0]);
    expect(screen.getByText("Delete loot row?")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(del).not.toHaveBeenCalled();
    expect(screen.queryByText("Delete loot row?")).not.toBeInTheDocument();
    expect(screen.getByText("Bat Guano")).toBeInTheDocument();
  });

  it("publishes selected rows when publish is configured", async () => {
    vi.spyOn(api, "loot").mockResolvedValue([orphaned]);
    const publish = vi.spyOn(api, "publishLoot").mockResolvedValue({
      published: 1,
      created: 1,
      replaced: 0,
      failed: 0,
      results: [{ loot_drop_id: 7, status: "ok", remote_action: "created", message: "created on remote" }],
    });
    render(<Loot />);

    await screen.findByText("Bat Guano");
    fireEvent.click(screen.getByLabelText("Select row 7"));
    fireEvent.click(screen.getByRole("button", { name: "Publish selected (1)" }));

    await waitFor(() => expect(publish).toHaveBeenCalledWith([7]));
    expect(screen.getByText(/Published 1 row/)).toBeInTheDocument();
  });

  it("hides the publish button when publishing is not configured", async () => {
    vi.spyOn(api, "status").mockResolvedValue({
      ...publishStatus(),
      publish: { configured: false, url: "" },
    });
    vi.spyOn(api, "loot").mockResolvedValue([orphaned]);
    render(<Loot />);

    await screen.findByText("Bat Guano");
    fireEvent.click(screen.getByLabelText("Select row 7"));
    const button = screen.getByRole("button", { name: /Publish selected/ }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });
});