import "./globals.css";

export const metadata = {
  title: "Figma → React Agent",
  description: "Convert Figma designs to React components using AI",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
