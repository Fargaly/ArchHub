// Compact stroke icons, one grammar across the existing plate controls.
(() => {
  const shapes = {
    home: 'M3 10 12 3l9 7v11h-6v-7H9v7H3z',
    workshop: 'M4 5h16v11H9l-5 4z M8 9h8 M8 12h5',
    canvas: 'M3 3h6v6H3z M15 15h6v6h-6z M9 6h8v9',
    library: 'M4 3v18 M8 3v18 M12 4l5-1 4 17-5 1z',
    brain: 'M12 7V5a3 3 0 0 0-6 0 4 4 0 0 0-3 6 4 4 0 0 0 1 7 4 4 0 0 0 8 2V7 M12 5a3 3 0 0 1 6 0 4 4 0 0 1 3 6 4 4 0 0 1-1 7 4 4 0 0 1-8 2 M6 11h3v5 M18 11h-3v5',
    docs: 'M5 3h10l4 4v14H5z M14 3v5h5 M8 12h8 M8 16h6',
    settings: 'm9 3 6 0 1 3 3 1 2 5-2 2v3l-5 4-3-1-3 1-5-4v-3l-2-2 2-5 3-1z M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
    search: 'm21 21-5-5 M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
    close: 'm6 6 12 12 M6 18 18 6',
    plus: 'M12 5v14 M5 12h14',
    minus: 'M5 12h14',
    play: 'm8 4 12 8-12 8z',
    stop: 'M6 6h12v12H6z',
    mic: 'M9 5a3 3 0 0 1 6 0v7a3 3 0 0 1-6 0z M5 10v2a7 7 0 0 0 14 0v-2 M12 19v3 M8 22h8',
    send: 'm22 2-7 20-4-9-9-4z M22 2 11 13',
    arrow: 'M5 12h14 m-5-5 5 5-5 5',
    back: 'M19 12H5 m5-5-5 5 5 5',
    edit: 'm16 3 5 5-12 12-6 1 1-6z M13 6l5 5',
    trash: 'M3 6h18 M9 6V3h6v3 M5 6l1 15h12l1-15 M10 10v7 M14 10v7',
    clock: 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0 M12 6v6l4 2',
    more: 'M5 12h.01 M12 12h.01 M19 12h.01',
    export: 'M12 16V3 m-4 4 4-4 4 4 M4 14v7h16v-7',
    refresh: 'M20 7a8 8 0 1 0 0 10 M20 3v5h-5',
    undo: 'M3 10h10a7 7 0 0 1 7 9 M3 10l5-5 M3 10l5 5',
    redo: 'M21 10H11a7 7 0 0 0-7 9 M21 10l-5-5 M21 10l-5 5',
    arrange: 'M3 4h6v6H3z M15 4h6v6h-6z M3 15h6v6H3z M15 15h6v6h-6z M9 7h6 M6 10v5 M18 10v5',
    group: 'M3 8V3h5 M16 3h5v5 M21 16v5h-5 M8 21H3v-5 M8 8h8v8H8z',
    fit: 'M3 9V3h6 M15 3h6v6 M21 15v6h-6 M9 21H3v-6',
    bell: 'M18 8a6 6 0 0 0-12 0v7l-3 3h18l-3-3z M10 21h4',
    tray: 'm3 13 3-9h12l3 9v7H3z M3 13h5l2 3h4l2-3h5',
    user: 'M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0 M4 22v-3a8 8 0 0 1 16 0v3',
    users: 'M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0 M3 21v-3a9 9 0 0 1 18 0v3',
    key: 'M15 8a5 5 0 1 1-10 0 5 5 0 0 1 10 0 M13 12l8 8 M17 16l3-3',
    folder: 'M3 5h7l2 3h9v13H3z',
    link: 'm10 14 4-4 M8 16l-2 2a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0 M16 8l2-2a4 4 0 0 1 6 6l-5 5a4 4 0 0 1-6 0',
    eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12 M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
    shield: 'm12 2 9 4v6c0 6-9 10-9 10S3 18 3 12V6z',
    palette: 'M12 3a9 9 0 1 0 0 18c4 0 1-5 4-5h2c5 0 4-13-6-13 M7 8h.01 M12 6h.01 M17 8h.01 M6 13h.01',
    update: 'M12 20V4 m-6 6 6-6 6 6 M4 20h16',
    code: 'm8 5-6 7 6 7 M16 5l6 7-6 7 M14 3l-4 18',
    check: 'm5 12 4 4L20 5',
    cloud: 'M7 18h11a5 5 0 0 0 0-10 7 7 0 0 0-13-1 5 5 0 0 0 2 11',
    pin: 'M9 3h6l-1 6 4 4H6l4-4z M12 13v8',
    voice: 'M3 9v6 M7 5v14 M12 2v20 M17 5v14 M21 9v6'
  };
  function Icon({
    name = 'arrow',
    size = 18,
    ...props
  }) {
    return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" {...props}><path d={shapes[name] || shapes.arrow} /></svg>;
  }
  window.AHIcon = Icon;
})();
