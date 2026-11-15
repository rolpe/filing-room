import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { readRecent } from "../lib/recent";
import { Icon, IconSprite } from "./Icons";
import { AddCompanyProvider } from "./AddCompany";

export function Shell() {
  const cov = useQuery({ queryKey: ["coverage"], queryFn: api.coverage });
  const devTools = !!cov.data?.dev_tools;  // the server's FILINGROOM_DEV_TOOLS switch
  const [recent, setRecent] = useState(readRecent);
  useEffect(() => {
    const on = () => setRecent(readRecent());
    window.addEventListener("filing-room:recent", on);
    return () => window.removeEventListener("filing-room:recent", on);
  }, []);
  const names = new Map((cov.data?.companies ?? []).map((c) => [c.ticker, c.name]));
  const recents = recent.filter((t) => names.has(t)).slice(0, 5);

  return (
    <AddCompanyProvider>
      <IconSprite />
      <div className="app">
        <aside className="rail">
          <NavLink className="wordmark" to="/" aria-label="filing-room, coverage"><Icon name="logo" /><span>filing-room</span></NavLink>
          <nav aria-label="Workspace">
            <NavLink className="item" to="/" end>
              <Icon name="list" /><span>Coverage</span>
            </NavLink>
          </nav>
          {recents.length > 0 && <>
            <h2>Recent</h2>
            <nav className="cos" aria-label="Recent companies">
              {recents.map((t) => (
                <NavLink key={t} className="co" to={`/c/${t}`} title={names.get(t)}>
                  <b>{t}</b><span>{names.get(t)}</span>
                </NavLink>
              ))}
            </nav>
          </>}
          {devTools && <>
            <h2>Developer</h2>
            <nav aria-label="Developer tools">
              <NavLink className="item" to="/evals"><Icon name="gauge" /><span>Evaluation</span></NavLink>
            </nav>
          </>}
          <div className="foot">
            <NavLink className="item" to="/usage"><Icon name="usage" /><span>Usage</span></NavLink>
          </div>
        </aside>
        <main className="main">
          <Outlet />
        </main>
      </div>
    </AddCompanyProvider>
  );
}
