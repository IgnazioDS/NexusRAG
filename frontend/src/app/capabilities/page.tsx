import {
  Boxes,
  CheckCircle2,
  Sparkles,
  Target,
  Users,
} from "lucide-react";
import { TopBar } from "@/components/layout/TopBar";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { PROJECT } from "@/lib/project";

export const metadata = { title: "Capabilities" };

export default function CapabilitiesPage() {
  return (
    <>
      <TopBar
        title="Capabilities"
        description={`Production scope and target audience for ${PROJECT.name}`}
      />
      <div className="flex-1 overflow-y-auto">
        <div className="page-enter mx-auto max-w-4xl space-y-5 p-6">
          {/* Pitch */}
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center gap-1.5 mb-2">
                <Badge variant="success">{PROJECT.stage}</Badge>
                <Badge variant="outline">{PROJECT.category}</Badge>
                <Badge variant="outline">{PROJECT.track}</Badge>
              </div>
              <CardTitle className="text-xl">{PROJECT.name}</CardTitle>
              <CardDescription className="leading-relaxed">
                {PROJECT.summary}
              </CardDescription>
            </CardHeader>
          </Card>

          {/* Problem + Why now */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Target className="h-3.5 w-3.5 text-brand" />
                  Problem
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-foreground-muted leading-relaxed">
                  {PROJECT.problem}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Sparkles className="h-3.5 w-3.5 text-brand" />
                  Why now
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-foreground-muted leading-relaxed">
                  {PROJECT.why_now}
                </p>
              </CardContent>
            </Card>
          </div>

          {/* What's shipping */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CheckCircle2 className="h-3.5 w-3.5 text-success" />
                What's shipping
              </CardTitle>
              <CardDescription>
                Production capabilities running today. Each item is wired to a
                feature flag with an ops kill switch — see the README feature
                matrix for the complete list.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ul className="space-y-3">
                {PROJECT.shipped.map((item, i) => (
                  <li
                    key={i}
                    className="flex items-start gap-3 rounded-md border border-border-subtle bg-surface-2 px-3 py-2.5"
                  >
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-success/15 text-2xs font-semibold text-success tabular-nums">
                      {i + 1}
                    </span>
                    <span className="text-sm text-foreground leading-relaxed">
                      {item}
                    </span>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>

          {/* Audience + Stack */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Users className="h-3.5 w-3.5 text-brand" />
                  Built for
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-foreground-muted leading-relaxed">
                  {PROJECT.users}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Boxes className="h-3.5 w-3.5 text-brand" />
                  Stack
                </CardTitle>
                <CardDescription>
                  Production stack — Postgres + pgvector for the local path,
                  Bedrock and Vertex for managed retrieval. Streaming agent
                  responses are powered by LangGraph.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-1.5">
                  {PROJECT.stack.map((s) => (
                    <Badge key={s} variant="muted">
                      {s}
                    </Badge>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </>
  );
}
