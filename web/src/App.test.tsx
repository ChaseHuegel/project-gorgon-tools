import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import App from "./App";

describe("App", () => {
  it("renders the heading", () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("no api"));
    render(<App />);
    expect(screen.getByRole("heading", { name: /gorgon-tracker/i })).toBeInTheDocument();
  });
});