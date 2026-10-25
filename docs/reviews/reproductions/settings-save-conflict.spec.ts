import { test, expect } from "@playwright/test";

// Historical diagnostic: passing reproduces the bug at dev 5f87f9c.
// Keep outside e2e discovery; implementation acceptance tests must expect success.
test("reproduce settings key conflict after a successful shortcut save", async ({
  page,
}) => {
  await page.goto("/settings");
  const pause = page.getByRole("combobox", {
    name: "Pause shortcut",
    exact: true,
  });
  await expect(pause).toBeEnabled();
  const initial = await pause.inputValue();
  await pause.selectOption(initial === "KeyP" ? "Space" : "KeyP");
  const first = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/v1/settings") && r.request().method() === "PUT",
  );
  await page
    .getByRole("button", { name: "Save shortcuts", exact: true })
    .click();
  expect((await first).status()).toBe(200);
  await expect(
    page.getByRole("button", { name: "Save shortcuts", exact: true }),
  ).toBeDisabled();
  const second = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/v1/settings") && r.request().method() === "PUT",
  );
  await page
    .getByRole("button", {
      name: "Save and create a new simulation",
      exact: true,
    })
    .click();
  const failure = await second;
  expect(failure.status()).toBe(409);
  expect((await failure.json()).error.code).toBe("IDEMPOTENCY_CONFLICT");
  await expect(page).toHaveURL(/\/settings$/);
  await expect(
    page.getByText(/Idempotency key was used for a different request/),
  ).toBeVisible();
});
