import { UiActionOptimisticPatch } from "./types";

export function applyOptimisticPatch<T extends Record<string, any>>(
  entity: T,
  patch: UiActionOptimisticPatch,
): T {
  // Apply optimistic patching without mutating the original object.
  if (entity.id !== patch.id) {
    return entity;
  }
  return { ...entity, ...patch.patch };
}
