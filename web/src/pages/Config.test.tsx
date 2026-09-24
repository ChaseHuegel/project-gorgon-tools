import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { Config as ConfigType, ConfigResponse } from "../api/types";
import ConfigPage from "./Config";

const config: ConfigType = {
  db: { path: "/db/gorgon.db" },
  capture: { enabled: true, tshark_path: "tshark", interface: "auto", ports: [], bpf: "" },
  chat: { log_dir: "/chat", tail: true, poll_interval_s: 1, tail_from_start: false },
  ocr: {
    enabled: true,
    tesseract_path: "tesseract",
    lang: "eng",
    zones: { region: [1, 2, 3, 4], interval_s: 5, heartbeat_s: 30 },
    targets: { region: [5, 6, 7, 8], interval_s: 0.5, heartbeat_s: null },
  },
  correlate: { buffer_seconds: 10, session_timeout: 3, retroactive_threshold: 0.9, target_fallback_seconds: 3, search_corroboration_seconds: 2 },
};

const response: ConfigResponse = { path: "/cfg/gorgon-tracker.toml", config };

describe("ConfigPage", () => {
  it("loads config and saves a single dotted change", async () => {
    vi.spyOn(api, "config").mockResolvedValue(response);
    const saveConfig = vi.spyOn(api, "saveConfig").mockResolvedValue(response);

    render(<ConfigPage />);
    expect(await screen.findByText("Configuration")).toBeInTheDocument();
    expect(screen.getByText(/Editing \/cfg\/gorgon-tracker.toml/)).toBeInTheDocument();

    const dbInput = await screen.findByDisplayValue("/db/gorgon.db");
    fireEvent.change(dbInput, { target: { value: "/db/new.db" } });

    const saveBtn = screen.getAllByRole("button", { name: "Save changes" })[0];
    fireEvent.click(saveBtn);

    await waitFor(() => expect(saveConfig).toHaveBeenCalledTimes(1));
    expect(saveConfig.mock.calls[0][0]).toEqual({ "db.path": "/db/new.db" });
  });
});