/** Opens the World following a citizen (at a past tick when one is given: the replayed world). */
export function mapLink(id: string, tick: number | null): string {
  return tick === null ? `/?follow=${id}` : `/?tick=${tick}&follow=${id}`;
}

/** Opens the World at a past tick. */
export function worldAt(tick: number): string {
  return `/?tick=${tick}`;
}

/** Keeps `?at=` on links between spectator pages while replaying. */
export function withAt(path: string, at: number | null): string {
  return at === null ? path : `${path}?at=${at}`;
}
