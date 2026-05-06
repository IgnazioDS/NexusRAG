import { CheckCircle2, Flag, Power, Sparkles } from "lucide-react";
import { TopBar } from "@/components/layout/TopBar";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  FEATURE_CATEGORIES,
  FEATURE_TOTAL,
  type FeatureStatus,
} from "@/lib/feature-matrix";

export const metadata = { title: "Feature Matrix" };

const STATUS_TONE: Record<FeatureStatus, "success" | "info" | "warning"> = {
  live: "success",
  beta: "info",
  preview: "warning",
};

export default function FeatureMatrixPage() {
  const liveCount = FEATURE_CATEGORIES.reduce(
    (sum, c) => sum + c.features.filter((f) => f.status === "live").length,
    0,
  );

  return (
    <>
      <TopBar
        title="Feature Matrix"
        description={`${liveCount} of ${FEATURE_TOTAL} features live in production · grouped by capability domain`}
      />
      <div className="dot-grid grid-fade flex-1 overflow-y-auto">
        <div className="page-enter mx-auto max-w-5xl space-y-6 p-6">
          {/* Header card */}
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center gap-1.5 mb-2">
                <Badge variant="success">
                  <CheckCircle2 className="h-3 w-3" />
                  {liveCount}/{FEATURE_TOTAL} live
                </Badge>
                <Badge variant="outline">Production</Badge>
                <Badge variant="outline">SOC 2 Ready</Badge>
              </div>
              <CardTitle className="text-xl">
                Every feature is config-flagged, kill-switchable, and
                tested.
              </CardTitle>
              <CardDescription className="leading-relaxed">
                The matrix below is sourced from the README{" "}
                <code className="font-mono text-foreground">Feature Matrix</code>{" "}
                section. Each entry maps to a real production capability with
                an env flag. Where a kill switch exists, it is named
                explicitly — operations can pause a feature surface without
                a code change.
              </CardDescription>
            </CardHeader>
          </Card>

          {/* Quick navigation */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Sparkles className="h-3.5 w-3.5 text-brand" />
                Jump to category
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-1.5">
                {FEATURE_CATEGORIES.map((c) => (
                  <a
                    key={c.id}
                    href={`#${c.id}`}
                    className="inline-flex items-center gap-1.5 rounded-md border border-border-subtle bg-surface-2 px-2.5 py-1 text-2xs font-medium text-foreground-muted hover:text-foreground hover:border-border transition-colors"
                  >
                    {c.label}
                    <span className="font-mono text-foreground-faint">
                      {c.features.length}
                    </span>
                  </a>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Categories */}
          {FEATURE_CATEGORIES.map((category) => (
            <Card key={category.id} id={category.id}>
              <CardHeader>
                <div className="flex items-baseline justify-between gap-3">
                  <CardTitle className="text-md">{category.label}</CardTitle>
                  <span className="text-2xs font-mono text-foreground-faint shrink-0">
                    {category.features.length}{" "}
                    {category.features.length === 1 ? "feature" : "features"}
                  </span>
                </div>
                <CardDescription className="leading-relaxed">
                  {category.description}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {category.features.map((f) => (
                    <div
                      key={f.name}
                      className="rounded-md border border-border-subtle bg-surface-2 p-3"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <p className="text-sm font-semibold text-foreground">
                              {f.name}
                            </p>
                            <Badge variant={STATUS_TONE[f.status]}>
                              {f.status}
                            </Badge>
                            {f.since && (
                              <span className="text-2xs font-mono text-foreground-faint">
                                since {f.since}
                              </span>
                            )}
                          </div>
                          <p className="mt-1 text-xs text-foreground-muted leading-relaxed">
                            {f.blurb}
                          </p>
                          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
                            {f.flag && (
                              <span className="inline-flex items-center gap-1 text-2xs font-mono text-foreground-faint">
                                <Flag className="h-3 w-3" />
                                {f.flag}
                              </span>
                            )}
                            {f.kill && (
                              <span className="inline-flex items-center gap-1 text-2xs font-mono text-warning">
                                <Power className="h-3 w-3" />
                                {f.kill}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </>
  );
}
