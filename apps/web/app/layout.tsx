import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "电商售后数据分析 Copilot",
  description: "A full-stack Agent project for ecommerce after-sales analysis."
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
