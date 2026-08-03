import { expect, test } from "@playwright/test";

const USER_WEB_URL = "http://127.0.0.1:3300";
const ADMIN_URL = "http://127.0.0.1:3320";

test.describe("WEB_ONLY MVP smoke", () => {
  test("registered web: home, recommendations, favorites, and buyer match surfaces render", async ({
    page,
  }) => {
    await page.goto(`${USER_WEB_URL}/home`);
    await expect(page.getByRole("heading", { name: "오늘의 추천 업체·부스" })).toBeVisible();
    await expect(page.getByText(/fallback 데이터를 표시/)).toBeVisible();

    await page.getByRole("link", { name: "추천 목록 전체 보기" }).click();
    await expect(page.getByRole("heading", { name: "추천 업체·부스 목록" })).toBeVisible();

    await page.getByRole("link", { name: "S-4 관심목록" }).click();
    await expect(page.getByRole("heading", { name: "관심목록" })).toBeVisible();

    await page.getByRole("link", { name: "S-6 바이어 매칭" }).click();
    await expect(page.getByRole("heading", { name: "바이어 매칭" })).toBeVisible();
    await expect(page.getByText(/연락처는 상담 수락 후 공개/).first()).toBeVisible();
  });

  test("guest web mobile: search entry uses GUEST_WEB mode without personal data inputs", async ({
    page,
  }) => {
    await page.goto(`${USER_WEB_URL}/search?q=%EB%AA%A9%EC%9E%AC&mode=GUEST_WEB`);

    await expect(page.getByRole("heading", { name: "자연어 검색" })).toBeVisible();
    await expect(page.getByLabel("검색 모드")).toHaveValue("GUEST_WEB");
    await expect(page.getByText(/MEETAI_EVENT_ID_NOT_CONFIGURED/)).toBeVisible();
    await expect(page.getByRole("link", { name: "지리산 목재가공" })).toBeVisible();

    await page.getByRole("link", { name: "지리산 목재가공" }).click();
    await expect(page.getByRole("heading", { name: "지리산 목재가공" })).toBeVisible();
    await expect(page.locator('input[type="email"], input[type="tel"], input[type="password"]')).toHaveCount(0);
  });

  test("admin: operation console exposes live API forms and contract-pending panels", async ({
    page,
  }) => {
    await page.goto(`${ADMIN_URL}/console`);

    await expect(page.getByRole("heading", { name: "운영 콘솔" })).toBeVisible();
    await expect(page.getByRole("button", { name: "승인 처리" })).toBeVisible();
    await expect(page.getByRole("button", { name: "상태 저장" })).toBeVisible();
    await expect(page.getByTestId("admin-area-exhibitor-product-review")).toContainText("운영");
    await expect(page.getByTestId("admin-area-buyer-verification")).toContainText("계약 대기");
    await expect(page.getByRole("region", { name: "기본 통계" }).getByText("사전등록 연계")).toBeVisible();
  });
});
