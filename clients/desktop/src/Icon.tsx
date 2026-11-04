type IconName =
  | "mic"
  | "phone"
  | "chat"
  | "sidebar"
  | "new"
  | "work"
  | "search"
  | "settings"
  | "plus"
  | "up"
  | "stop"
  | "globe"
  | "close";

const paths: Record<IconName, string> = {
  mic: "M9 5a3 3 0 0 1 6 0v7a3 3 0 0 1-6 0V5ZM6 10v2a6 6 0 0 0 12 0v-2M12 18v4M8 22h8",
  phone:
    "M8 3h8a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2ZM10 17h4",
  chat: "M4 5h16v12H9l-5 4V5ZM8 9h8M8 13h5",
  sidebar:
    "M9 4v16M5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Z",
  new: "M13 5H6a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-7M16 4l4 4M10 14l1-4 7-7 4 4-7 7-5 1Z",
  work: "M9 6V4h6v2M4 7h16v13H4V7ZM4 12h16M10 12v3h4v-3",
  search: "M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z",
  settings:
    "m9 3-1 3-3 1-2 3 2 2-1 3 3 3 3-1 2 2 3-1 1-3 3-1 1-3-2-2 1-3-3-2-3 1-2-2ZM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z",
  plus: "M12 5v14M5 12h14",
  up: "M12 19V5M5 12l7-7 7 7",
  stop: "M6 6h12v12H6Z",
  globe:
    "M21 12H3M12 3a15 15 0 0 1 0 18 15 15 0 0 1 0-18ZM21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
  close: "m6 6 12 12M6 18 18 6",
};

export function Icon({ name }: { name: IconName }) {
  return (
    <svg
      className="icon"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}
