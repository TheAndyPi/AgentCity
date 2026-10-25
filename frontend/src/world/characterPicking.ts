/** Through-building highlights must receive events before the covering city. */
export function prioritizeCharacterHighlights<
  T extends { object: { userData: Record<string, unknown> } },
>(hits: T[]): T[] {
  return [
    ...hits.filter((hit) => hit.object.userData.characterHighlight === true),
    ...hits.filter((hit) => hit.object.userData.characterHighlight !== true),
  ];
}
