import * as Sentry from "@sentry/nextjs";
import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

export function generateMetadata(): Metadata {
  return {
    title: "Buoy Retriever",
    description: "Manage fetching and processing of IOOS data",
    other: {
      ...Sentry.getTraceData(),
    },
  };
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="font-sans-serif">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
