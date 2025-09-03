import { createContext, useContext, useEffect, useMemo, useState } from "react";

type Theme = "concussive" | "ethereal" | "kinetic";
type Ctx = { theme: Theme; setTheme: (t: Theme) => void; };

const ThemeCtx = createContext<Ctx>({ theme: "ethereal", setTheme: () => {} });
export const useTheme = () => useContext(ThemeCtx);

export default function ThemeProvider({ children }: { children: React.ReactNode }){
  const [theme, setTheme] = useState<Theme>("ethereal");
  const value = useMemo(() => ({ theme, setTheme }), [theme]);

  useEffect(() => {
    document.body.classList.remove("theme-concussive","theme-ethereal","theme-kinetic");
    document.body.classList.add(`theme-${theme}`);
  }, [theme]);

  return <ThemeCtx.Provider value={value}>{children}</ThemeCtx.Provider>;
}
