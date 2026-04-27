import type { Metadata, Viewport } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";

import { ThemeProvider } from "@/components/providers/theme-provider";
import { Toaster } from "@/components/providers/toaster";
import { CommandPaletteProvider } from "@/components/layout/CommandPalette";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Sidebar } from "@/components/layout/Sidebar";

export const metadata: Metadata = {
  metadataBase: new URL("https://nexusrag-lyart.vercel.app"),
  title: {
    default: "NexusRAG — Multi-tenant RAG agent platform",
    template: "%s · NexusRAG",
  },
  description:
    "Production-grade multi-tenant RAG platform with streaming agent responses, audit logging, and pluggable retrieval backends.",
  applicationName: "NexusRAG",
  authors: [{ name: "Ignazio De Santis" }],
  keywords: [
    "RAG",
    "agent platform",
    "vector search",
    "FastAPI",
    "Next.js",
    "Vercel",
    "multi-tenant",
  ],
  openGraph: {
    type: "website",
    title: "NexusRAG Dashboard",
    description:
      "Production-grade multi-tenant RAG platform with streaming responses and audit logging.",
    siteName: "NexusRAG",
  },
  twitter: {
    card: "summary",
    title: "NexusRAG",
    description:
      "Production-grade multi-tenant RAG platform with streaming responses and audit logging.",
  },
  icons: {
    icon: [{ url: "/favicon.svg", type: "image/svg+xml" }],
  },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#08080d" },
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
  ],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${GeistMono.variable}`}
      suppressHydrationWarning
    >
      <body className="font-sans">
        <ThemeProvider>
          <TooltipProvider delayDuration={150}>
            <CommandPaletteProvider>
              <div className="flex h-screen overflow-hidden bg-background text-foreground">
                <Sidebar />
                <main className="flex flex-1 flex-col overflow-hidden">
                  {children}
                </main>
              </div>
              <Toaster />
            </CommandPaletteProvider>
          </TooltipProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
