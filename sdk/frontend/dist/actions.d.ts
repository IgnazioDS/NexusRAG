import { UiActionOptimisticPatch } from "./types";
export declare function applyOptimisticPatch<T extends Record<string, any>>(entity: T, patch: UiActionOptimisticPatch): T;
