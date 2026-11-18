def stylesheet(dark: bool) -> str:
    if dark:
        bg, panel, border, text, muted, rail = "#111b29", "#1a2738", "#33465b", "#eef4fb", "#a9bbcd", "#111e30"
        accent, selection, header = "#3ebaaa", "#254d51", "#243548"
        action_text, hover = "#092a27", "#5ad6c0"
    else:
        bg, panel, border, text, muted, rail = "#f2f6fa", "#ffffff", "#d5e1eb", "#142a3d", "#50677c", "#102538"
        accent, selection, header = "#087768", "#d7efe9", "#e9f0f6"
        action_text, hover = "#ffffff", "#086458"
    return f"""
    QWidget {{ color: {text}; font-size: 13px; }}
    QMainWindow, QDialog, QWidget#workspace {{ background: {bg}; }}
    QWidget#rail {{ background: {rail}; }}
    QWidget#card {{ background: {panel}; border: 1px solid {border}; border-radius: 12px; }}
    QLabel#product {{ color: #f1fafb; font-size: 23px; font-weight: 700; }}
    QLabel#productZh {{ color: #a6becb; font-size: 13px; }}
    QLabel#title {{ font-size: 28px; font-weight: 700; }}
    QLabel#stat {{ font-size: 25px; font-weight: 700; }}
    QLabel#muted {{ color: {muted}; }}
    QPushButton {{ border: 1px solid {border}; background: {panel}; padding: 7px 13px;
                   border-radius: 7px; min-height: 22px; }}
    QPushButton:hover {{ background: {header}; }}
    QPushButton#primary {{ background: {accent}; color: {action_text}; border-color: {accent};
                           font-weight: 700; }}
    QPushButton#primary:hover {{ background: {hover}; border-color: {hover}; }}
    QPushButton:disabled, QComboBox:disabled {{ color: {muted}; background: {header}; }}
    QPushButton#nav {{ background: transparent; color: #c9dae5; border: 0;
                       text-align: left; padding: 11px 14px; font-weight: 600; }}
    QPushButton#nav:hover, QPushButton#nav:checked {{ background: #254355; color: #ffffff; }}
    QLineEdit, QComboBox {{ border: 1px solid {border}; background: {panel};
                             border-radius: 6px; padding: 6px 9px; min-height: 21px; }}
    QComboBox QAbstractItemView {{ background: {panel}; selection-background-color: {selection}; }}
    QTableView, QTreeWidget {{ background: {panel}; alternate-background-color: {bg};
                              border: 1px solid {border}; border-radius: 7px;
                              selection-background-color: {selection}; selection-color: {text}; }}
    QHeaderView::section {{ background: {header}; color: {text}; border: 0;
                            border-bottom: 1px solid {border}; padding: 8px; font-weight: 600; }}
    QProgressBar {{ border: 0; border-radius: 4px; background: {header}; height: 8px; }}
    QProgressBar::chunk {{ background: {accent}; border-radius: 4px; }}
    QScrollArea {{ border: 0; }}
    QStatusBar {{ background: {bg}; color: {muted}; }}
    """

