import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import ImportExport from "./ImportExport";

const names: Awaited<ReturnType<typeof api.names>> = {
  enabled: true,
  data_dir: "/tmp/names",
  zones_count: 100,
  monsters_count: 50,
  zones_path: "/tmp/names/zones.txt",
  monsters_path: "/tmp/names/monsters.txt",
  zones_source: "bundled",
  monsters_source: "bundled",
  zones_mtime_ms: null,
  monsters_mtime_ms: null,
};

describe("ImportExportPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "names").mockResolvedValue(names);
  });

  it("clears all data after confirming the dialog", async () => {
    const clear = vi
      .spyOn(api, "clearData")
      .mockResolvedValue({ ok: true, cleared: { sessions: 2, loot_drops: 12 } });
    render(<ImportExport />);

    const button = await screen.findByRole("button", { name: "Clear all data" });
    fireEvent.click(button);

    expect(screen.getByText("Clear all data?")).toBeInTheDocument();
    const confirm = screen.getAllByRole("button", { name: "Clear all data" }).pop()!;
    fireEvent.click(confirm);

    await waitFor(() => expect(clear).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/Cleared 14 rows across 2 tables/)).toBeInTheDocument();
    expect(screen.queryByText("Clear all data?")).not.toBeInTheDocument();
  });

  it("cancelling the dialog does nothing", async () => {
    const clear = vi.spyOn(api, "clearData").mockResolvedValue({ ok: true, cleared: {} });
    render(<ImportExport />);

    fireEvent.click(await screen.findByRole("button", { name: "Clear all data" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(clear).not.toHaveBeenCalled();
    expect(screen.queryByText("Clear all data?")).not.toBeInTheDocument();
  });
});