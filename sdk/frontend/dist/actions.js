export function applyOptimisticPatch(entity, patch) {
    // Apply optimistic patching without mutating the original object.
    if (entity.id !== patch.id) {
        return entity;
    }
    return { ...entity, ...patch.patch };
}
