# Changelog

## Version 0.22.0

Fix enabling debug mode. Before this fix, sometimes it was impossible to enable debug mode.

## Version 0.20.0

Partial fix related to Q2305573 (user login in multi-company environment):
- everything should work fine unless try to restrict access to website model via generic_security_restriction model

## Version 0.19.1

Fix bug related to Q2304559

## Version 0.13.0

- Added ability to set restrictions for contextual server actions

## Version 0.9.0

Add restriction option to show the only specific menus

## Version 0.8.0

Added ability to restrict access to the records of any model for specific user.

## Version 0.7.0

- Added ability to set restrictions for action windows

## Version 0.3.0

#### Version 0.3.0
- Added ability to restirct access to any report / priniting form for any user.

## Version 0.1.11

Added the ability to set field options :
- 'no_open': (in read mode) do not render as a link,

- 'no_create': it is `'no_quick_create'` and `'no_create_edit'` combined,

- 'no_quick_create': remove the `"Create 'foo' "` option,

- 'no_create_edit': Remove the  `"Create and edit..."` option.

## Version 0.1.6

#### Version 0.1.6
- Added the ability to hide a stat button witch includes the selected field.

