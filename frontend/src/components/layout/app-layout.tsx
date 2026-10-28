import { NavLink, Outlet } from 'react-router';

const LINKS = [
  { to: '/', label: 'World' },
  { to: '/town', label: 'Town' },
  { to: '/gallery', label: 'Gallery' },
  { to: '/status', label: 'Status' },
];

export function AppLayout() {
  return (
    <div className="flex h-svh flex-col">
      <header className="bg-background flex items-center gap-4 border-b px-4 py-2">
        <span className="font-medium">Pebble</span>
        <nav className="flex gap-3 text-sm">
          {LINKS.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end
              className={({ isActive }) =>
                isActive ? 'text-foreground' : 'text-muted-foreground'
              }
            >
              {link.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <div className="min-h-0 flex-1">
        <Outlet />
      </div>
    </div>
  );
}
