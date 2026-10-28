import { NavLink, Outlet } from 'react-router';

// the town walk stays at /town, off the menu
const LINKS = [
  { to: '/', label: 'World', end: true },
  { to: '/people', label: 'People', end: false },
  { to: '/conversations', label: 'Conversations', end: true },
  { to: '/gallery', label: 'Gallery', end: true },
  { to: '/status', label: 'Status', end: true },
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
              end={link.end}
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
