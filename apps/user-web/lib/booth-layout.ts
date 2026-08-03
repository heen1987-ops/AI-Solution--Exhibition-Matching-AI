export const BOOTH_LAYOUT_STATUS = "DRAFT_REFERENCE" as const;
export const BOOTH_LAYOUT_SCOPE = "EXCO_HALL_3_SINGLE_HALL" as const;

export type ProvisionalBoothCell = {
  code: string;
  width: "SINGLE" | "DOUBLE";
  status: "PROVISIONAL";
};

export type ProvisionalBoothColumn = {
  id: "Q" | "R" | "S";
  label: string;
  booths: readonly ProvisionalBoothCell[];
};

function booth(code: string, width: ProvisionalBoothCell["width"] = "SINGLE"): ProvisionalBoothCell {
  return { code, width, status: "PROVISIONAL" };
}

export const PROVISIONAL_BOOTH_COLUMNS: readonly ProvisionalBoothColumn[] = [
  {
    id: "Q",
    label: "Q 부스열",
    booths: [
      booth("Q-31", "DOUBLE"),
      booth("Q-25", "DOUBLE"),
      booth("Q-19", "DOUBLE"),
      booth("Q-16"), booth("Q-18"),
      booth("Q-13"), booth("Q-15"),
      booth("Q-09"), booth("Q-10"),
      booth("Q-07"), booth("Q-08"),
      booth("Q-01"), booth("Q-04"),
      booth("Q-02", "DOUBLE"),
    ],
  },
  {
    id: "R",
    label: "R 부스열",
    booths: [
      booth("R-31", "DOUBLE"),
      booth("R-25", "DOUBLE"),
      booth("R-22"), booth("R-23"),
      booth("R-19"), booth("R-20"),
      booth("R-16"), booth("R-17"),
      booth("R-14"), booth("R-15"),
      booth("R-07"), booth("R-08"),
      booth("R-05"), booth("R-06"),
      booth("R-01", "DOUBLE"),
    ],
  },
  {
    id: "S",
    label: "S 부스열",
    booths: [
      booth("S-31", "DOUBLE"),
      booth("S-25", "DOUBLE"),
      booth("S-19", "DOUBLE"),
      booth("S-18", "DOUBLE"),
      booth("S-14", "DOUBLE"),
      booth("S-13", "DOUBLE"),
      booth("S-07", "DOUBLE"),
      booth("S-01", "DOUBLE"),
    ],
  },
] as const;
