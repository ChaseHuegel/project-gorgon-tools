import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import Status from "./Status";

const fake = {
  db_path: "/tmp/x/gorgon.db",
  config_path: "/tmp/x/gorgon-tracker.toml",
  config_db_path: "/tmp/x/gorgon.db",
  sessions_total: 3,
  open_session_id: 2,
  open_session_counts: { loot: 10, sources: 4 },
  daemon: { pid: 4242, running: true, pidfile: "/tmp/x/gorgon-tracker.pid" },
  warnings: ["Chat tailing has no log directory."],
};

describe("StatusPage", () => {
  it("renders live counters and warnings", async () => {
    vi.spyOn(api, "status").mockResolvedValue(fake);
    render(<Status />);
    expect(await screen.findByText("Capture status")).toBeInTheDocument();
    expect(await screen.findByText("Stop capture")).toBeInTheDocument();
    expect(screen.getByText("Chat tailing has no log directory.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("loot")).toBeInTheDocument());
  });

  it("calls daemonStop when the daemon is running", async () => {
    const spyStop = vi.spyOn(api, "daemonStop").mockResolvedValue(fake.daemon);
    vi.spyOn(api, "status").mockResolvedValue(fake);
    render(<Status />);
    const btn = await screen.findByText("Stop capture");
    btn.click();
    await waitFor(() => expect(spyStop).toHaveBeenCalled());
  });
});