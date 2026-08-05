import { describe, expect, it } from "vitest";

import {
  buildDemoRoute,
  DEMO_EXHIBITORS,
  DEMO_VISITOR_PROFILE,
  getDemoBoothNotePosition,
  orderDemoRouteByAisle,
  rankDemoExhibitors,
  selectDemoRecommendations,
} from "./booth-map-simulation";

describe("booth map simulation", () => {
  it("creates exactly 50 clearly synthetic exhibitors with unique booth numbers", () => {
    expect(DEMO_EXHIBITORS).toHaveLength(50);
    expect(new Set(DEMO_EXHIBITORS.map((item) => item.boothNumber)).size).toBe(50);
    expect(DEMO_EXHIBITORS.every((item) => item.simulationOnly && item.name.includes("(가상)"))).toBe(true);
  });

  it("keeps every simulated booth inside the inferred hall canvas", () => {
    expect(DEMO_EXHIBITORS.every((item) => item.x > 0 && item.x < 100 && item.y > 15 && item.y < 90)).toBe(true);
  });

  it("keeps every selected interest represented in the top recommendations", () => {
    const ranked = rankDemoExhibitors(DEMO_VISITOR_PROFILE.interests);
    const topTen = selectDemoRecommendations(ranked, DEMO_VISITOR_PROFILE.interests, 10);

    expect(topTen).toHaveLength(10);
    expect(new Set(topTen.map((item) => item.category))).toEqual(new Set(DEMO_VISITOR_PROFILE.interests));
  });

  it("builds a unique six-stop route from the recommended candidates", () => {
    const ranked = rankDemoExhibitors(DEMO_VISITOR_PROFILE.interests);
    const recommended = selectDemoRecommendations(ranked, DEMO_VISITOR_PROFILE.interests, 10);
    const route = buildDemoRoute(recommended, 6);

    expect(route).toHaveLength(6);
    expect(new Set(route.map((item) => item.id)).size).toBe(6);
    expect(route.every((item) => recommended.some((candidate) => candidate.id === item.id))).toBe(true);
  });

  it("walks each aisle before turning into the next row", () => {
    const ranked = rankDemoExhibitors(DEMO_VISITOR_PROFILE.interests);
    const recommended = selectDemoRecommendations(ranked, DEMO_VISITOR_PROFILE.interests, 10);
    const numberedStops = buildDemoRoute(recommended, 6);
    const markerNumber = new Map(numberedStops.map((item, index) => [item.id, index + 1]));
    const visitRoute = orderDemoRouteByAisle(numberedStops);

    expect(visitRoute.map((item) => markerNumber.get(item.id))).toEqual([1, 3, 2, 4, 5, 6]);
    expect(visitRoute.slice(1).every((item, index) => item.y <= visitRoute[index].y)).toBe(true);
  });

  it("keeps every booth memo inside the hall canvas", () => {
    const positions = DEMO_EXHIBITORS.map(getDemoBoothNotePosition);

    expect(positions.every((position) => position.left >= 2 && position.left <= 70)).toBe(true);
    expect(positions.every((position) => position.top >= 18 && position.top <= 76)).toBe(true);
  });
});
