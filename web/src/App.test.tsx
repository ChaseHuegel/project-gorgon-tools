import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("App", () => {
  it("renders the index of navigation links", () => {
    render(<App />);
    expect(screen.getAllByText("gorgon-tracker").length).toBeGreaterThan(0);
    expect(screen.getByText("Status")).toBeInTheDocument();
  });
});