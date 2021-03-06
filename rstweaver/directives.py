
from docutils.parsers.rst import Directive, directives
from docutils import nodes
from structure import Block
from uuid import uuid4
import re
from highlight import highlight_as

class WeaverDirective(Directive):
    
    def __init__(self, context, name, *a, **b):
        Directive.__init__(self, *a, **b)
        self.context        = context
        self.directive_name = name
    
    def run(self):
        args    = self.arguments
        options = self.options
        content = self.content
        
        key = (
            self.directive_name,
            tuple(args),
            tuple(options.items()),
            tuple(content)
        )
        
        output = self.context.run_cache(
            key,
            lambda: self.handle(args, options, content)
        )
        return output
    
    def handle(self, args, options, content):
        raise NotImplementedError

class NoninteractiveDirective(WeaverDirective):
    
    def __init__(self, context, name, language, *a, **b):
        WeaverDirective.__init__(self, context, name, *a, **b)
        self.language = language
        
    def handle(self, args, options, content):
        file_like_args    = [arg for arg in args if arg.find('.') != -1]
        command_like_args = [arg for arg in args if arg.find('.') == -1]
        
        def cmd(s):
            return directives.choice(s, [
                'exec', 'done', 'restart', 'noeval', 'redo',
                'join', 'noecho', 'new', 'recall'
            ])
        commands = map(cmd, command_like_args)

        if len(file_like_args) > 0: source_name = file_like_args[0]
        elif 'new' in commands:
            source_name = 'main' + str(unique_block_id()) + self.language.extension()
        else: source_name = 'main' + self.language.extension()
        
        was_empty = self.context.is_empty(source_name)
        was_lines = self.context.count_lines(source_name)
 
        if 'recall' in commands:
            input_display  = self.do_recall(source_name, commands, options, content)
            output_display = None
        else:
            input_display  = self.do_mods(source_name, commands, options, content)
            output_display = self.do_run(source_name, commands, options, content)
            
        if 'join' in commands: header_node = nodes.inline()
        else:
            cont = '(cont)' if not was_empty else ''
            header_text = '     %s %s\n\n' % (source_name, cont)
            header_node = nodes.inline(
                header_text, header_text, classes=['file-header']
            )
        
        if input_display != None:
            source_nodes = []
            for sblock in input_display:
                if sblock.name == None:
                    btext = sblock.text()
                    if 'highlight' in options:
                        hlbtext = highlight_as(btext, options['highlight'])
                    else:
                        hlbtext = self.language.highlight(sblock.text())
                    source_nodes +=  hlbtext
                else:
                    source_nodes += [nodes.inline('',
                        '[... %s ...]' % sblock.name,
                        classes = ['omission']
                    ), nodes.inline('\n', '\n')]
                    
            if self.language.number_lines():
                source_nodes = add_line_numbers(source_nodes, was_lines+1)
            
            source_node = nodes.literal_block(
                classes=['code', 'code-' + self.directive_name])
            source_node += header_node
            for n in source_nodes:
                source_node += n
        else:
            source_node = None
        
        if output_display != None:
            if isinstance(output_display, str):
                output = strip_blank_lines(output_display)
                try:
                    output = output.decode('utf-8')
                except:
                    output = filter(lambda c: ord(c)<128, output)
                output_node = nodes.literal_block(output, output,
                    classes=['run-output', 'run-output-' + self.directive_name]
                )
            else:
                output_node = output_display
        else:
            output_node = None
        
        if 'noecho' in commands: return [ ]
        else:
            result = []
            if source_node != None: result.append(source_node)
            if output_node != None: result.append(output_node)
        
            return result
    
    def do_recall(self, source, commands, options, content):
        block_name = (self.options['name']
            if 'name' in self.options else None
        )
        text = self.context.recall(source, block_name)
        return [Block.just_text(text)]
    
    def do_mods(self, source, commands, options, content):
        cx = self.context
        
        if 'restart' in commands:
            cx.restart(source)

        block_name = (self.options['name']
            if 'name' in self.options
            else None
        )
        
        redo = 'redo' in commands
        into = options['in'] if 'in' in options else None
        after = options['after'] if 'after' in options else None

        lines = map(str, content)
        
        block = self.expand_subparts(lines, block_name)
        
        if not ('noeval' in commands):
            cx.feed(source, block, redo, after, into)
            
        return block.subblocks
    
    def do_run(self, source, commands, options, content):
        if 'done' in commands:
            return self.context.compile(source, self.language)
        
        elif 'exec' in commands:
            return self.context.run(source, self.language)
    
    def expand_subparts(self, lines, block_name):
        leading = ()
        parts   = ()
        
        while 1:
            if len(lines) == 0:
                if len(leading) > 0:
                    back = Block.with_lines(None, leading)
                    parts = parts + (back,)
                break
            
            else:
                head = lines[0]
                rest = lines[1:]
                match = re.match(r'^\s*\<\<\<([^\>]*)\>\>\>\s*$', head)
                
                if match != None:
                    back = Block.with_lines(None, leading)
                    leading = ()
                    
                    takeout = Block.empty(match.groups(1)[0])
                    parts = parts + (back,takeout)
                
                else:
                    head = re.subn(r'\<\<\<\<([^\>]*)\>\>\>\>', r'<<<\1>>>', head)[0]
                    leading = leading + (head,)
                
                lines = rest
        
        return Block.with_parts(block_name, parts)

class InteractiveDirective(WeaverDirective):

    def __init__(self, context, name, language, *a, **b):
        WeaverDirective.__init__(self, context, name,  *a, **b)
        self.language = language
    
    def handle(self, args, options, content):
        cx = self.context

        file_like_args = args
        lines = map(str, content)
        
        output_lines = cx.run_interactive(file_like_args, lines, self.language)
        if len(output_lines) < len(lines):
            output_lines = output_lines + ([''] * (len(lines) - len(output_lines)))
        
        sess_nodes = []
            
        for k in range(len(lines)):
            input_node = nodes.inline(classes = ['interactive-input'])
            input_node += nodes.inline('', self.language.interactive_prompt())
            for n in self.language.highlight(lines[k].rstrip().lstrip()):
                input_node += n
            
            output_line = output_lines[k]
            output_line = filter(
                lambda c: ord(c) < 128, output_line
            )
            output_node = nodes.inline('', output_line,
                classes = ['interactive-output'])
            
            sess_nodes += [input_node, nodes.inline('\n','\n'), output_node]
            if k < len(lines)-1:
                sess_nodes += [nodes.inline('\n\n','\n\n')]
        
        all_node = nodes.literal_block(classes=['interactive-session'])
        for n in sess_nodes:
            all_node += n
            
        return [all_node]

class WriteAllDirective(WeaverDirective):
    
    def __init__(self, context, name, *a, **b):
        WeaverDirective.__init__(self, context, name, *a, **b)
    
    def handle(self, args, options, content):
        self.context.write_all()
        return []

def strip_blank_lines(text):
    text = re.sub(r'^\s*\n', '', text)
    text = re.sub(r'\n\s*$', '', text)
    return text

def add_line_numbers(toks, start):
    def ln(n):
        return nodes.inline('', '%3d  ' % n, classes=['lineno'])
    
    def gen():
        yield ln(start)
        line = start + 1
        for j in range(len(toks)):
            node = toks[j]
            
            text = node.rawsource
            parts = text.split('\n')
            
            if len(parts) == 1:
                yield node
            else:
                classes = node.attributes['classes']
                
                for k in range(len(parts)):
                    yield nodes.inline('', parts[k], classes=classes)
                    if k < len(parts)-1:
                        yield nodes.inline('\n', '\n')
                        if k < len(parts)-2 or j < len(toks)-1:
                            yield ln(line)
                        line += 1
        
    return list(gen())

def unique_block_id():
    return uuid4().hex[:4]

