/** The message to show for anything a promise rejected with. */
export function messageOf(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
