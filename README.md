# Fusion hub exporter

Saves a copy of everything in your Fusion hub in formats other programs can open. Made for people who are leaving Fusion.

| What you have in Fusion | What you get |
|---|---|
| 3D designs and assemblies | STEP files |
| 2D drawings | PDF and DWG files |
| Electronics | EAGLE files |

## Install (once)

1. Unzip the download so you have a folder named **HubExporter**.
2. Open Fusion and press **Shift+S**. A window called **Scripts and Add-Ins** opens.
3. Select the **Add-Ins** tab, then select the green **+** and choose the **HubExporter** folder.
4. Select **Hub exporter** in the list and choose **Run**.

That's it. You can close the window.

## Export your hub

1. In the Data Panel, open the hub you want to save.
2. In the **Design** workspace, open the **Tools** tab and choose **Export hub**.
3. Choose the folder where you want your files, then choose **OK**.
4. Read the message and choose **Yes**.

Then wait. A big hub can take hours, and Fusion can't be used until it's done. Keep Fusion open and your computer awake.

When it finishes, a report opens in your browser. Check the **Needs your attention** list at the top. It shows anything that could not be saved, and why.

## If something goes wrong

If Fusion stops or you cancel, open Fusion, choose **Export hub** and pick the same folder. It carries on where it left off and says how far it got.

## Good to know

- Only the latest version of each file is saved.
- Files that aren't Fusion files (such as uploaded PDFs or Word files) aren't saved. The report lists them so you can download them yourself.
- Your files are saved in folders that match your hub: hub, then project, then folders. The report is saved in the hub's folder.

---

Drawing and electronics export use features that older versions of Fusion don't have. The confirmation message tells you if yours is missing one.

Based on [Project Archiver](https://github.com/tapnair/Project-Archiver) by Patrick Rainsberry, used under the Apache License 2.0. See `LICENSE` and `NOTICE`.
