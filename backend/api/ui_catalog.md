| Type | Use | Props | Children |
|---|---|---|---|
| `Card` | Container card for content sections. Use for forms/content boxes, NOT for page headers. | `title`: string; `description`: string; `maxWidth`: "sm", "md", "lg" or "full"; `centered`: boolean; `className`: string | yes |
| `Stack` | Flex container for layouts | `direction`: "horizontal" or "vertical"; `gap`: "none", "sm", "md", "lg" or "xl"; `align`: "start", "center", "end" or "stretch"; `justify`: "start", "center", "end", "between" or "around"; `className`: string | yes |
| `Grid` | Grid layout (1-6 columns) | `columns`: number; `gap`: "sm", "md", "lg" or "xl"; `className`: string | yes |
| `Separator` | Visual separator line | `orientation`: "horizontal" or "vertical" | no |
| `Tabs` | Tab navigation. Use { $bindState } on value for active tab binding. | `tabs`: array of {label: string, value: string}, required; `defaultValue`: string; `value`: string | yes |
| `Accordion` | Collapsible sections. Items as [{title, content}]. Type 'single' (default) or 'multiple'. | `items`: array of {title: string, content: string}, required; `type`: "single" or "multiple" | no |
| `Collapsible` | Collapsible section with trigger. Children render inside. | `title`: string, required; `defaultOpen`: boolean | yes |
| `Dialog` | Modal dialog. Set openPath to a boolean state path. Use setState to toggle. | `title`: string, required; `description`: string; `openPath`: string, required | yes |
| `Drawer` | Bottom sheet drawer. Set openPath to a boolean state path. Use setState to toggle. | `title`: string, required; `description`: string; `openPath`: string, required | yes |
| `Carousel` | Horizontally scrollable carousel of cards. | `items`: array of {title: string, description: string}, required | no |
| `Table` | Data table. columns: header labels. rows: 2D array of cell strings, e.g. [["Alice","admin"],["Bob","user"]]. | `columns`: array of string, required; `rows`: array of array of string, required; `caption`: string | no |
| `Heading` | Heading text (h1-h4) | `text`: string, required; `level`: "h1", "h2", "h3" or "h4" | no |
| `Text` | Paragraph text | `text`: string, required; `variant`: "body", "caption", "muted", "lead" or "code" | no |
| `Image` | Image component. Renders an img tag when src is provided, otherwise a placeholder. | `src`: string; `alt`: string, required; `width`: number; `height`: number | no |
| `Avatar` | User avatar with fallback initials | `src`: string; `name`: string, required; `size`: "sm", "md" or "lg" | no |
| `Badge` | Status badge | `text`: string, required; `variant`: "default", "secondary", "destructive" or "outline" | no |
| `Alert` | Alert banner | `title`: string, required; `message`: string; `type`: "info", "success", "warning" or "error" | no |
| `Progress` | Progress bar (value 0-100) | `value`: number, required; `max`: number; `label`: string | no |
| `Skeleton` | Loading placeholder skeleton | `width`: string; `height`: string; `rounded`: boolean | no |
| `Spinner` | Loading spinner indicator | `size`: "sm", "md" or "lg"; `label`: string | no |
| `Tooltip` | Hover tooltip. Shows content on hover over text. | `content`: string, required; `text`: string, required | no |
| `Popover` | Popover that appears on click of trigger. | `trigger`: string, required; `content`: string, required | no |
| `Input` | Text input field. Use { $bindState } on value for two-way binding. Use checks for validation (e.g. required, email, minLength). validateOn controls timing (default: blur). | `label`: string, required; `name`: string, required; `type`: "text", "email", "password" or "number"; `placeholder`: string; `value`: string; `checks`: array of {type: string, message: string, args?: object}; `validateOn`: "change", "blur" or "submit" | no |
| `Textarea` | Multi-line text input. Use { $bindState } on value for binding. Use checks for validation. validateOn controls timing (default: blur). | `label`: string, required; `name`: string, required; `placeholder`: string; `rows`: number; `value`: string; `checks`: array of {type: string, message: string, args?: object}; `validateOn`: "change", "blur" or "submit" | no |
| `Select` | Dropdown select input. Use { $bindState } on value for binding. Use checks for validation. validateOn controls timing (default: change). | `label`: string, required; `name`: string, required; `options`: array of string, required; `placeholder`: string; `value`: string; `checks`: array of {type: string, message: string, args?: object}; `validateOn`: "change", "blur" or "submit" | no |
| `Checkbox` | Checkbox input. Use { $bindState } on checked for binding. Use checks for validation. validateOn controls timing (default: change). | `label`: string, required; `name`: string, required; `checked`: boolean; `checks`: array of {type: string, message: string, args?: object}; `validateOn`: "change", "blur" or "submit" | no |
| `Radio` | Radio button group. Use { $bindState } on value for binding. Use checks for validation. validateOn controls timing (default: change). | `label`: string, required; `name`: string, required; `options`: array of string, required; `value`: string; `checks`: array of {type: string, message: string, args?: object}; `validateOn`: "change", "blur" or "submit" | no |
| `Switch` | Toggle switch. Use { $bindState } on checked for binding. Use checks for validation. validateOn controls timing (default: change). | `label`: string, required; `name`: string, required; `checked`: boolean; `checks`: array of {type: string, message: string, args?: object}; `validateOn`: "change", "blur" or "submit" | no |
| `Slider` | Range slider input. Use { $bindState } on value for binding. | `label`: string; `min`: number; `max`: number; `step`: number; `value`: number | no |
| `Button` | Clickable button. Bind on.press for handler. | `label`: string, required; `variant`: "primary", "secondary" or "danger"; `disabled`: boolean | no |
| `Link` | Anchor link. Bind on.press for click handler. | `label`: string, required; `href`: string, required | no |
| `DropdownMenu` | Dropdown menu with trigger button and selectable items. Use { $bindState } on value for selected item binding. | `label`: string, required; `items`: array of {label: string, value: string}, required; `value`: string | no |
| `Toggle` | Toggle button. Use { $bindState } on pressed for state binding. | `label`: string, required; `pressed`: boolean; `variant`: "default" or "outline" | no |
| `ToggleGroup` | Group of toggle buttons. Type 'single' (default) or 'multiple'. Use { $bindState } on value. | `items`: array of {label: string, value: string}, required; `type`: "single" or "multiple"; `value`: string | no |
| `ButtonGroup` | Segmented button group. Use { $bindState } on selected for selected value. | `buttons`: array of {label: string, value: string}, required; `selected`: string | no |
| `Pagination` | Page navigation. Use { $bindState } on page for current page number. | `totalPages`: number, required; `page`: number | no |
